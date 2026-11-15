using System.Net;

namespace Book_Finder.Application.Email;

// Account mail content (plan member-center C1). Pure functions: the caller passes the recipient, the display name, the absolute link
// and the link's validity. No password is ever a parameter, and the HTML body encodes the display name and the link.
public static class AccountEmailTemplates
{
    private const string VerificationSubject = "好想找書 - 請驗證你的 Email";
    private const string PasswordResetSubject = "好想找書 - 重設密碼";
    private const string PasswordChangedSubject = "好想找書 - 你的密碼已變更";
    private const string IgnoreNotice = "如果不是你本人申請，可以忽略這封信。";

    public static EmailMessage EmailVerification(string to, string displayName, string link, TimeSpan validity)
    {
        var greeting = Greeting(displayName);
        var validityText = FormatValidity(validity);
        var text = $"{greeting}\n\n"
            + "感謝你註冊好想找書。請點擊以下連結完成 Email 驗證，完成後即可登入：\n\n"
            + $"{link}\n\n"
            + $"此連結 {validityText} 內有效，只能使用一次。\n";
        var html = "<p>" + Encode(greeting) + "</p>"
            + "<p>感謝你註冊好想找書。請點擊以下連結完成 Email 驗證，完成後即可登入：</p>"
            + $"<p><a href=\"{Encode(link)}\">{Encode(link)}</a></p>"
            + $"<p>此連結 {Encode(validityText)} 內有效，只能使用一次。</p>";
        return new EmailMessage(to, VerificationSubject, text, html);
    }

    public static EmailMessage PasswordReset(string to, string displayName, string link, TimeSpan validity)
    {
        var greeting = Greeting(displayName);
        var validityText = FormatValidity(validity);
        var text = $"{greeting}\n\n"
            + "我們收到重設密碼的申請。請點擊以下連結設定新密碼：\n\n"
            + $"{link}\n\n"
            + $"此連結 {validityText} 內有效，只能使用一次。\n\n"
            + IgnoreNotice + "\n";
        var html = "<p>" + Encode(greeting) + "</p>"
            + "<p>我們收到重設密碼的申請。請點擊以下連結設定新密碼：</p>"
            + $"<p><a href=\"{Encode(link)}\">{Encode(link)}</a></p>"
            + $"<p>此連結 {Encode(validityText)} 內有效，只能使用一次。</p>"
            + "<p>" + Encode(IgnoreNotice) + "</p>";
        return new EmailMessage(to, PasswordResetSubject, text, html);
    }

    // Sent after a reset committed, so the owner learns of a change they did not make. It carries no token: the recovery link is the
    // public forgot-password page. changedAtText is already formatted in Taipei time by the caller.
    public static EmailMessage PasswordChanged(string to, string displayName, string changedAtText, string forgotPasswordLink)
    {
        var greeting = Greeting(displayName);
        var changed = $"你的好想找書帳號密碼已於 {changedAtText}（台北時間）重設。所有裝置都已登出，MCP 連線授權也已撤銷，請用新密碼重新登入。";
        var warning = "如果不是你本人操作，請立即到以下頁面重新設定密碼：";
        var text = $"{greeting}\n\n{changed}\n\n{warning}\n\n{forgotPasswordLink}\n";
        var html = "<p>" + Encode(greeting) + "</p>"
            + "<p>" + Encode(changed) + "</p>"
            + "<p>" + Encode(warning) + "</p>"
            + $"<p><a href=\"{Encode(forgotPasswordLink)}\">{Encode(forgotPasswordLink)}</a></p>";
        return new EmailMessage(to, PasswordChangedSubject, text, html);
    }

    // WebUtility leaves apostrophes alone, so they are encoded too; the link can then sit in a quoted attribute whichever quote is used.
    private static string Encode(string value) => WebUtility.HtmlEncode(value).Replace("'", "&#39;");

    // The display name is free text from the member, so it is only trimmed here; the HTML body encodes it where it is used.
    private static string Greeting(string displayName)
    {
        var name = displayName.Trim();
        return name.Length == 0 ? "會員您好：" : $"{name} 您好：";
    }

    // Whole hours read as hours ("24 小時"); everything else reads as minutes ("90 分鐘").
    private static string FormatValidity(TimeSpan validity)
    {
        var totalMinutes = (int)Math.Round(validity.TotalMinutes);
        return totalMinutes % 60 == 0 && totalMinutes >= 60
            ? $"{totalMinutes / 60} 小時"
            : $"{totalMinutes} 分鐘";
    }
}
