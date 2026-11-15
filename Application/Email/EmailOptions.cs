using System.Net.Mail;

namespace Book_Finder.Application.Email;

// Outbound mail settings bound from the "Email" section (plan member-center C1). The default is None, which sends nothing at all.
public sealed class EmailOptions
{
    public const string SectionName = "Email";

    public EmailProvider Provider { get; set; } = EmailProvider.None;

    // The sender address. Required for Ses; a display name ("好想找書 <noreply@...>") is allowed.
    public string? From { get; set; }

    // The AWS region of the SES identity. Required for Ses.
    public string? Region { get; set; }

    // Where the Pickup provider writes .eml files. A relative path is resolved against the content root.
    public string? PickupDirectory { get; set; }

    // Null when the combination is usable. The message names the setting to fix, so the startup failure is actionable.
    public string? ValidationError(bool verificationEnabled)
    {
        if (verificationEnabled && Provider == EmailProvider.None)
            return "EmailVerification:Enabled 為 true 時，Email:Provider 不可為 None";

        switch (Provider)
        {
            case EmailProvider.Ses:
                if (string.IsNullOrWhiteSpace(From))
                    return "Email:Provider 為 Ses 時必須設定 Email:From";
                if (!IsMailAddress(From))
                    return "Email:From 必須是有效的 email 地址";
                if (string.IsNullOrWhiteSpace(Region))
                    return "Email:Provider 為 Ses 時必須設定 Email:Region";
                return null;
            case EmailProvider.Pickup:
                return string.IsNullOrWhiteSpace(PickupDirectory)
                    ? "Email:Provider 為 Pickup 時必須設定 Email:PickupDirectory"
                    : null;
            default:
                return null;
        }
    }

    private static bool IsMailAddress(string value)
    {
        try
        {
            _ = new MailAddress(value);
            return true;
        }
        catch (FormatException)
        {
            return false;
        }
    }
}

public enum EmailProvider
{
    // Nothing is sent. Any send fails, so a flow cannot pretend that mail went out.
    None,

    // Amazon SES v2, with credentials from the default AWS chain (instance role).
    Ses,

    // Writes each message to a file under Email:PickupDirectory. Local development only.
    Pickup,
}

// Email verification switch (plan member-center D-A). Off by default: registration and login behave as before.
public sealed class EmailVerificationOptions
{
    public const string SectionName = "EmailVerification";

    public bool Enabled { get; set; } = false;
}
