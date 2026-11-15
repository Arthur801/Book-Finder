using System.Globalization;
using System.IdentityModel.Tokens.Jwt;
using Book_Finder.Application.Identity;
using Book_Finder.Infrastructure.Persistence;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.Identity;

// All auth wiring lives here: options, DI registrations, the JWT bearer scheme (cookie-based) and antiforgery.
public static class AuthServiceCollectionExtensions
{
    public static IServiceCollection AddBookFinderAuth(this IServiceCollection services, IConfiguration configuration)
    {
        services.TryAddSingleton(TimeProvider.System);

        services.AddOptions<JwtOptions>()
            .Bind(configuration.GetSection(JwtOptions.SectionName))
            .Validate(JwtOptions.HasValidSigningKey, "Jwt:SigningKey 缺少或短於 32 bytes")
            .ValidateOnStart();

        services.AddSingleton<IPasswordHashing, AspNetPasswordHashing>();
        services.AddScoped<IUserStore, EfUserStore>();
        services.AddScoped<AccountService>();
        services.AddSingleton<AuthTokenIssuer>();

        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer();
        services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
            .Configure<IOptions<JwtOptions>, TimeProvider>((bearer, jwt, time) =>
            {
                bearer.MapInboundClaims = false;
                bearer.TokenValidationParameters = jwt.Value.CreateValidationParameters();
                // The framework's default lifetime check reads the system clock, so tests cannot control expiry.
                // This one reads the injected TimeProvider and keeps ClockSkew = 0 (identity-auth.md §5).
                bearer.TokenValidationParameters.LifetimeValidator = (notBefore, expires, _, _) =>
                {
                    var now = time.GetUtcNow().UtcDateTime;
                    if (expires is null || now >= expires.Value)
                        return false;
                    return notBefore is null || now >= notBefore.Value;
                };
                bearer.Events = new JwtBearerEvents
                {
                    OnTokenValidated = ValidateAuthVersionAsync,
                    OnMessageReceived = context =>
                    {
                        // Cookie only. Without a cookie, NoResult stops the handler from falling back to the Authorization header.
                        var token = context.Request.Cookies[AuthCookie.Name];
                        if (string.IsNullOrEmpty(token))
                            context.NoResult();
                        else
                            context.Token = token;
                        return Task.CompletedTask;
                    },
                    OnChallenge = context =>
                    {
                        context.HandleResponse();
                        return WriteChallengeAsync(context.HttpContext);
                    },
                };
            });
        services.AddAuthorization();

        services.AddAntiforgery(options =>
        {
            options.HeaderName = "RequestVerificationToken";
            options.Cookie.SecurePolicy = CookieSecurePolicy.Always;
        });
        services.Configure<MvcOptions>(options =>
        {
            options.Filters.Add(new AutoValidateAntiforgeryTokenAttribute());
            options.Filters.Add<AntiforgeryProblemDetailsFilter>();
            options.Filters.Add<ApiExceptionProblemDetailsFilter>();
        });

        return services;
    }

    // A cookie is signed and unexpired, but the server still decides: the user must exist and the auth_version claim must
    // match the stored AuthVersion. One primary-key read per authenticated request, no cache, so a bump or delete takes
    // effect on the next request. A cookie without the claim was issued before this check existed, so it counts as 0.
    // Email verification is not checked here: cookies are only issued to verified users (plan D-A).
    private static async Task ValidateAuthVersionAsync(TokenValidatedContext context)
    {
        var http = context.HttpContext;
        var sub = context.Principal?.FindFirst(JwtRegisteredClaimNames.Sub)?.Value;
        if (!Guid.TryParse(sub, out var userId))
        {
            RejectAuthCookie(context);
            return;
        }

        var user = await http.RequestServices.GetRequiredService<IUserStore>().FindByIdAsync(userId, http.RequestAborted);
        var tokenVersion = ParseAuthVersion(context.Principal?.FindFirst(JwtOptions.AuthVersionClaim)?.Value);
        if (user is null || tokenVersion != user.AuthVersion)
            RejectAuthCookie(context);
    }

    // A missing claim is version 0 (cookies issued before this check). A malformed claim is null, which matches no stored version.
    private static int? ParseAuthVersion(string? claim)
    {
        if (claim is null)
            return 0;
        return int.TryParse(claim, NumberStyles.None, CultureInfo.InvariantCulture, out var version) ? version : null;
    }

    // Deleting the cookie stops the browser from sending it again. The JwtBearer challenge then answers /api with 401 and pages with a login redirect.
    private static void RejectAuthCookie(TokenValidatedContext context)
    {
        AuthCookie.Delete(context.HttpContext.Response);
        context.Fail("Auth cookie is no longer valid for this user.");
    }

    // /api/* gets a 401 ProblemDetails; pages go to the login page and come back to the same location.
    private static Task WriteChallengeAsync(HttpContext http)
    {
        if (ApiRequest.IsApi(http.Request))
        {
            var problem = http.RequestServices.GetRequiredService<ProblemDetailsFactory>().CreateProblemDetails(
                http,
                statusCode: StatusCodes.Status401Unauthorized,
                title: "請先登入",
                type: "/errors/unauthenticated");
            http.Response.StatusCode = StatusCodes.Status401Unauthorized;
            return http.Response.WriteAsJsonAsync(problem, options: null, contentType: "application/problem+json");
        }

        // Only GET/HEAD pages can be reopened after login. A POST-only route as returnUrl would make the browser GET it
        // (405 or an error page), so non-GET challenges go to the login page without a returnUrl.
        if (!HttpMethods.IsGet(http.Request.Method) && !HttpMethods.IsHead(http.Request.Method))
        {
            http.Response.Redirect("/account/login");
            return Task.CompletedTask;
        }

        var returnUrl = (http.Request.PathBase + http.Request.Path).Add(http.Request.QueryString);
        http.Response.Redirect($"/account/login?returnUrl={Uri.EscapeDataString(returnUrl)}");
        return Task.CompletedTask;
    }
}
