using System.Collections.Immutable;
using System.Security.Claims;
using Book_Finder.Application.Identity;
using Book_Finder.Domain.Entities;
using Book_Finder.Infrastructure.Identity;
using Book_Finder.Infrastructure.Identity.OAuth;
using Book_Finder.Models;
using Microsoft.AspNetCore;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Mvc;
using Microsoft.IdentityModel.Tokens;
using OpenIddict.Abstractions;
using OpenIddict.Server.AspNetCore;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Book_Finder.Controllers;

// OAuth Authorization Server endpoints (MCP-ADR-007, plan mcp-server section 3.4, D-09, D-10): authorize with explicit consent,
// the consent POST and the token endpoint. The endpoints run in OpenIddict passthrough mode, so OpenIddict parses the request and
// this controller decides the outcome. Every outcome is a SignIn or a Forbid on the OpenIddict scheme; the website cookie is only read.
// When Mcp:Enabled is false OpenIddict is not registered, no request is extracted, and each action answers 404 like /mcp.
public class OAuthController(IUserStore users, IConfiguration configuration) : Controller
{
    // The OpenIddict managers are registered only with Mcp:Enabled, so they are resolved per request, after ServerRequest() has
    // succeeded. A constructor parameter would make every /oauth request fail with 500 when MCP is off.
    private IOpenIddictApplicationManager Applications =>
        HttpContext.RequestServices.GetRequiredService<IOpenIddictApplicationManager>();

    private IOpenIddictAuthorizationManager Authorizations =>
        HttpContext.RequestServices.GetRequiredService<IOpenIddictAuthorizationManager>();

    private const string LoginPath = "/account/login";
    private const string AuthorizePath = "/oauth/authorize";
    private const string AcceptSubmit = "submit.Accept";
    private const string DenySubmit = "submit.Deny";

    [HttpGet("/oauth/authorize")]
    public async Task<IActionResult> Authorize(CancellationToken cancellationToken)
    {
        var request = ServerRequest();
        if (request is null)
            return NotFound();

        // The website user comes from the default scheme (the bf_auth cookie), never from the OpenIddict scheme.
        var user = await SignedInUserAsync(cancellationToken);
        if (user is null)
        {
            if (request.HasPromptValue(PromptValues.None))
                return Reject(Errors.LoginRequired, "The user is not logged in.");
            return Redirect(LoginRedirect(LocalRequestUrl()));
        }

        // Re-authentication is not offered, so prompt=login is answered with login_required instead of a login loop.
        if (request.HasPromptValue(PromptValues.Login))
            return Reject(Errors.LoginRequired, "Re-authentication (prompt=login) is not supported.");
        if (!RequestsOnlyRecommendScope(request))
            return Reject(Errors.InvalidScope, "Only the books:recommend scope can be requested.");

        var application = await Applications.FindByClientIdAsync(request.ClientId!, cancellationToken);
        if (application is null)
            return BadRequest("Unknown client.");

        var permanent = await FindPermanentAsync(application, user, cancellationToken);
        if (permanent.Count == 0 && request.HasPromptValue(PromptValues.None))
            return Reject(Errors.ConsentRequired, "Interactive user consent is required.");

        // D-10: a permanent authorization covers the request, so approve without asking again. prompt=consent always asks.
        if (permanent.Count > 0 && !request.HasPromptValue(PromptValues.Consent))
        {
            var identity = CreateIdentity(user);
            identity.SetAuthorizationId(await Authorizations.GetIdAsync(permanent[^1], cancellationToken));
            return SignIn(new ClaimsPrincipal(identity), OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
        }

        // The consent page must never be framed: a hidden "allow" click on a framed page would grant access (clickjacking, RFC 6819
        // 4.4.1.9). The site sets no framing policy of its own, so this page sets both the legacy header and the CSP directive.
        Response.Headers.XFrameOptions = "DENY";
        Response.Headers.ContentSecurityPolicy = "frame-ancestors 'none'";
        return View("Consent", new OAuthConsentViewModel
        {
            ClientName = await Applications.GetDisplayNameAsync(application, cancellationToken) ?? request.ClientId!,
            Email = user.Email,
        });
    }

    // The consent form's buttons. The form carries the original request as hidden fields, so OpenIddict reads it from the form.
    // A POST with neither button is refused, so only an explicit approval creates a grant.
    [HttpPost("/oauth/authorize")]
    public async Task<IActionResult> Submit(CancellationToken cancellationToken)
    {
        var request = ServerRequest();
        if (request is null)
            return NotFound();

        if (Request.Form.ContainsKey(DenySubmit))
            return Deny();
        if (Request.Form.ContainsKey(AcceptSubmit))
            return await Accept(request, cancellationToken);
        return BadRequest();
    }

    private async Task<IActionResult> Accept(OpenIddictRequest request, CancellationToken cancellationToken)
    {
        // An expired session returns to the authorize request this form carried (rebuilt without the token and submit fields).
        var user = await SignedInUserAsync(cancellationToken);
        if (user is null)
            return Redirect(LoginRedirect(FormAuthorizeUrl()));

        if (!RequestsOnlyRecommendScope(request))
            return Reject(Errors.InvalidScope, "Only the books:recommend scope can be requested.");

        var application = await Applications.FindByClientIdAsync(request.ClientId!, cancellationToken);
        if (application is null)
            return BadRequest("Unknown client.");

        // Approval creates the permanent authorization once; later requests for the same user, client and scope skip consent (D-10).
        var identity = CreateIdentity(user);
        var permanent = await FindPermanentAsync(application, user, cancellationToken);
        var authorization = permanent.Count > 0
            ? permanent[^1]
            : await Authorizations.CreateAsync(
                identity: identity,
                subject: user.Id.ToString(),
                client: (await Applications.GetIdAsync(application, cancellationToken))!,
                type: AuthorizationTypes.Permanent,
                scopes: GrantedScopes,
                cancellationToken: cancellationToken);

        identity.SetAuthorizationId(await Authorizations.GetIdAsync(authorization, cancellationToken));
        return SignIn(new ClaimsPrincipal(identity), OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
    }

    // Deny: OpenIddict turns a Forbid without an error into access_denied on the client's redirect_uri.
    private IActionResult Deny() => Forbid(OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);

    // Public clients send no antiforgery token and no secret; PKCE is what protects the exchange. Antiforgery is enforced globally
    // for forms, but this endpoint is called by the client application, not by a browser form.
    [HttpPost("/oauth/token"), IgnoreAntiforgeryToken, Produces("application/json")]
    public async Task<IActionResult> Token(CancellationToken cancellationToken)
    {
        var request = ServerRequest();
        if (request is null)
            return NotFound();

        if (!request.IsAuthorizationCodeGrantType() && !request.IsRefreshTokenGrantType())
            return Reject(Errors.UnsupportedGrantType, "Only the authorization_code and refresh_token grants are supported.");

        // The authorization code or refresh token carries the principal OpenIddict stored at approval time.
        var result = await HttpContext.AuthenticateAsync(OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
        if (result is not { Succeeded: true, Principal: not null })
            return Reject(Errors.InvalidGrant, "The token is no longer valid.");

        // A deleted user must not keep a code or refresh token alive (D-10 revocation by deletion).
        var user = await users.FindByIdAsync(result.Principal.CurrentUserId(), cancellationToken);
        if (user is null)
            return Reject(Errors.InvalidGrant, "The user no longer exists.");

        // Copy the stored claims (scopes, resource, authorization) and refresh the subject and name from the current user.
        var identity = new ClaimsIdentity(
            result.Principal.Claims,
            authenticationType: TokenValidationParameters.DefaultAuthenticationType,
            nameType: Claims.Name,
            roleType: Claims.Role);
        identity.SetClaim(Claims.Subject, user.Id.ToString())
                .SetClaim(Claims.Name, user.Email);
        identity.SetDestinations(GetDestinations);

        return SignIn(new ClaimsPrincipal(identity), OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
    }

    // The OpenIddict request of this call. Without Mcp:Enabled no OpenIddict server is registered, so there is no request to read
    // and the endpoint answers 404, the same as the unmapped /mcp path.
    private OpenIddictRequest? ServerRequest() =>
        configuration.GetValue<bool>("Mcp:Enabled") ? HttpContext.GetOpenIddictServerRequest() : null;

    // The website user for this request, or null when no valid bf_auth cookie is present or the account no longer exists.
    private async Task<User?> SignedInUserAsync(CancellationToken cancellationToken)
    {
        var result = await HttpContext.AuthenticateAsync();
        if (result is not { Succeeded: true, Principal: not null })
            return null;
        return await users.FindByIdAsync(result.Principal.CurrentUserId(), cancellationToken);
    }

    // Permanent authorizations for this user and client that include the requested scope. The client argument is the application's
    // internal id (IOpenIddictApplicationManager.GetIdAsync), not the client_id string.
    private async Task<List<object>> FindPermanentAsync(object application, User user, CancellationToken cancellationToken) =>
        await Authorizations.FindAsync(
            subject: user.Id.ToString(),
            client: (await Applications.GetIdAsync(application, cancellationToken))!,
            status: Statuses.Valid,
            type: AuthorizationTypes.Permanent,
            scopes: RequestedScopes,
            cancellationToken: cancellationToken).ToListAsync(cancellationToken);

    // Only books:recommend exists. A request without scope means books:recommend (MCP-B14), so the check is over the requested values.
    private static bool RequestsOnlyRecommendScope(OpenIddictRequest request) =>
        request.GetScopes().All(scope => scope == OAuthServiceCollectionExtensions.RecommendScope);

    // What is granted is fixed: books:recommend (the only scope the request may ask for, checked above), plus offline_access so the
    // client receives a refresh token (D-09). offline_access is never requested by the client, so the grant does not depend on it.
    private static readonly ImmutableArray<string> GrantedScopes =
        [OAuthServiceCollectionExtensions.RecommendScope, Scopes.OfflineAccess];

    private static readonly ImmutableArray<string> RequestedScopes = [OAuthServiceCollectionExtensions.RecommendScope];

    // The identity OpenIddict turns into the code or tokens. The subject is the Book-Finder user id (CurrentUserId reads it back),
    // the name is the account email, and the protected resource is the configured MCP URL (RFC 8707).
    private ClaimsIdentity CreateIdentity(User user)
    {
        var identity = new ClaimsIdentity(
            authenticationType: TokenValidationParameters.DefaultAuthenticationType,
            nameType: Claims.Name,
            roleType: Claims.Role);
        identity.SetClaim(Claims.Subject, user.Id.ToString())
                .SetClaim(Claims.Name, user.Email);
        identity.SetScopes(GrantedScopes);
        identity.SetResources(OAuthServiceCollectionExtensions.ResourceOf(configuration));
        identity.SetDestinations(GetDestinations);
        return identity;
    }

    // sub and name go into the access token only. The ID token is not issued because openid is not a supported scope.
    private static IEnumerable<string> GetDestinations(Claim claim)
    {
        switch (claim.Type)
        {
            case Claims.Subject or Claims.Name:
                yield return Destinations.AccessToken;
                yield break;

            default:
                yield break;
        }
    }

    // The error response OpenIddict builds from these properties, on the client's redirect_uri when OpenIddict can use it.
    private IActionResult Reject(string error, string description) => Forbid(
        authenticationSchemes: OpenIddictServerAspNetCoreDefaults.AuthenticationScheme,
        properties: new AuthenticationProperties(new Dictionary<string, string?>
        {
            [OpenIddictServerAspNetCoreConstants.Properties.Error] = error,
            [OpenIddictServerAspNetCoreConstants.Properties.ErrorDescription] = description,
        }));

    private string LocalRequestUrl() => (Request.PathBase + Request.Path).Add(Request.QueryString);

    // The authorize URL a POST came from. Hidden fields carry the OAuth parameters; the antiforgery token and the submit button are dropped.
    private string FormAuthorizeUrl() =>
        AuthorizePath + QueryString.Create(Request.Form.Where(field =>
            field.Key != "__RequestVerificationToken" && field.Key != AcceptSubmit && field.Key != DenySubmit));

    // Sends the user to login and back to this same local URL afterwards (SafeReturnUrl accepts it).
    private static string LoginRedirect(string returnUrl) => $"{LoginPath}?returnUrl={Uri.EscapeDataString(returnUrl)}";
}
