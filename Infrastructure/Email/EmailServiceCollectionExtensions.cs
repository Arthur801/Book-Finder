using Amazon;
using Amazon.SimpleEmailV2;
using Book_Finder.Application.Email;
using Book_Finder.Application.Site;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Options;

namespace Book_Finder.Infrastructure.Email;

// Email wiring (plan member-center C1): the Site, EmailVerification and Email settings, and the IEmailSender chosen by Email:Provider.
// Every adapter is built from settings here, so no credential is read from configuration; SES uses the default AWS chain.
public static class EmailServiceCollectionExtensions
{
    public static IServiceCollection AddBookFinderEmail(this IServiceCollection services, IConfiguration configuration, IHostEnvironment environment)
    {
        services.TryAddSingleton(TimeProvider.System);

        services.AddOptions<SiteOptions>()
            .Bind(configuration.GetSection(SiteOptions.SectionName))
            .Validate(SiteOptions.HasValidPublicBaseUrl, "Site:PublicBaseUrl 必須是 https 網址（開發可用 http://localhost）")
            .ValidateOnStart();
        services.AddSingleton<SiteUrlBuilder>();

        services.AddOptions<EmailVerificationOptions>()
            .Bind(configuration.GetSection(EmailVerificationOptions.SectionName));

        // The provider rules depend on the verification switch, so the switch is read here and handed to the validator.
        var verificationEnabled = configuration.GetValue<bool>($"{EmailVerificationOptions.SectionName}:Enabled");
        services.AddOptions<EmailOptions>()
            .Bind(configuration.GetSection(EmailOptions.SectionName))
            .ValidateOnStart();
        services.AddSingleton<IValidateOptions<EmailOptions>>(new EmailOptionsValidator(verificationEnabled, environment.IsDevelopment()));

        services.AddSingleton<IEmailSender>(provider =>
        {
            var email = provider.GetRequiredService<IOptions<EmailOptions>>().Value;
            return email.Provider switch
            {
                EmailProvider.Ses => new SesEmailSender(
                    new AmazonSimpleEmailServiceV2Client(RegionEndpoint.GetBySystemName(email.Region)),
                    email.From!,
                    provider.GetRequiredService<ILogger<SesEmailSender>>()),
                EmailProvider.Pickup => new PickupDirectoryEmailSender(
                    Path.GetFullPath(Path.Combine(environment.ContentRootPath, email.PickupDirectory!)),
                    email.From ?? "noreply@localhost",
                    provider.GetRequiredService<TimeProvider>()),
                _ => new NoEmailSender(),
            };
        });
        return services;
    }

    // Pickup only writes files, so outside Development it would drop every mail without an error; the host refuses to start instead.
    private sealed class EmailOptionsValidator(bool verificationEnabled, bool development) : IValidateOptions<EmailOptions>
    {
        public ValidateOptionsResult Validate(string? name, EmailOptions options)
        {
            if (options.Provider == EmailProvider.Pickup && !development)
                return ValidateOptionsResult.Fail("Email:Provider 為 Pickup 只能用於 Development 環境");

            var error = options.ValidationError(verificationEnabled);
            return error is null ? ValidateOptionsResult.Success : ValidateOptionsResult.Fail(error);
        }
    }
}
