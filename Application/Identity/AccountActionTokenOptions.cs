namespace Book_Finder.Application.Identity;

// Account action token settings bound from the "AccountActionTokens" configuration section (plan member-center-email-verification section C2).
public sealed class AccountActionTokenOptions
{
    public const string SectionName = "AccountActionTokens";

    // Minimum time between two issues of the same purpose for one user. Measured from the newest token row, consumed or not.
    public TimeSpan RequestInterval { get; set; } = TimeSpan.FromHours(1);

    // How long an email verification link stays usable after it is issued.
    public TimeSpan EmailVerificationLifetime { get; set; } = TimeSpan.FromHours(24);

    // How long a password reset link stays usable. Equal to RequestInterval, so an expired link never blocks a new request for longer than the window.
    public TimeSpan PasswordResetLifetime { get; set; } = TimeSpan.FromHours(1);

    // Checked at startup so an invalid value stops the host instead of issuing tokens that expire at once or never throttle.
    public static bool HasValidRequestInterval(AccountActionTokenOptions options) => options.RequestInterval > TimeSpan.Zero;

    public static bool HasValidEmailVerificationLifetime(AccountActionTokenOptions options) => options.EmailVerificationLifetime > TimeSpan.Zero;

    public static bool HasValidPasswordResetLifetime(AccountActionTokenOptions options) => options.PasswordResetLifetime > TimeSpan.Zero;
}
