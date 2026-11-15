using Book_Finder.Application.Email;

namespace UnitTests;

// Member-center email templates (plan member-center-email-verification C1). The HTML body carries the display name and the link,
// so both are HTML-encoded; the templates take no password, and the durations are parameters, not constants.
public sealed class AccountEmailTemplatesTests
{
    private const string Link = "https://khwebsc.com/account/verify-email?token=abc&lang=zh";

    [Fact]
    public void Verification_mail_is_addressed_to_the_recipient_with_a_traditional_chinese_subject()
    {
        var message = AccountEmailTemplates.EmailVerification("member@example.com", "小明", Link, TimeSpan.FromHours(24));

        Assert.Equal("member@example.com", message.To);
        Assert.Contains("Email", message.Subject);
        Assert.Contains("驗證", message.Subject);
    }

    [Fact]
    public void Verification_mail_states_the_24_hour_validity_and_the_link()
    {
        var message = AccountEmailTemplates.EmailVerification("member@example.com", "小明", Link, TimeSpan.FromHours(24));

        Assert.Contains("24 小時", message.TextBody);
        Assert.Contains(Link, message.TextBody);
        Assert.Contains("24 小時", message.HtmlBody);
    }

    [Fact]
    public void Reset_mail_states_the_one_hour_validity_and_the_ignore_notice()
    {
        var message = AccountEmailTemplates.PasswordReset("member@example.com", "小明", Link, TimeSpan.FromHours(1));

        Assert.Equal("member@example.com", message.To);
        Assert.Contains("1 小時", message.TextBody);
        Assert.Contains("如果不是你本人申請，可以忽略這封信", message.TextBody);
        Assert.Contains("如果不是你本人申請，可以忽略這封信", message.HtmlBody);
        Assert.Contains("重設密碼", message.Subject);
    }

    [Theory]
    [InlineData(60, "1 小時")]
    [InlineData(90, "90 分鐘")]
    [InlineData(24 * 60, "24 小時")]
    [InlineData(45, "45 分鐘")]
    public void Validity_text_follows_the_given_duration(int minutes, string expected)
    {
        var message = AccountEmailTemplates.PasswordReset("member@example.com", "小明", Link, TimeSpan.FromMinutes(minutes));

        Assert.Contains(expected, message.TextBody);
        Assert.Contains(expected, message.HtmlBody);
    }

    [Fact]
    public void Password_changed_notice_states_the_time_the_effects_and_how_to_recover()
    {
        var message = AccountEmailTemplates.PasswordChanged("member@example.com", "小明", "2026-11-15 12:00", "https://khwebsc.com/account/password/forgot");

        Assert.Equal("member@example.com", message.To);
        Assert.Equal("好想找書 - 你的密碼已變更", message.Subject);
        Assert.Contains("小明 您好", message.TextBody);
        Assert.Contains("2026-11-15 12:00（台北時間）", message.TextBody);
        Assert.Contains("所有裝置都已登出", message.TextBody);
        Assert.Contains("MCP", message.TextBody);
        Assert.Contains("如果不是你本人操作", message.TextBody);
        Assert.Contains("https://khwebsc.com/account/password/forgot", message.TextBody);
        Assert.Contains("href=\"https://khwebsc.com/account/password/forgot\"", message.HtmlBody);
        Assert.DoesNotContain("token=", message.TextBody);
    }

    [Fact]
    public void Password_changed_notice_encodes_a_malicious_display_name_in_html()
    {
        var message = AccountEmailTemplates.PasswordChanged("member@example.com", "<script>x</script>", "2026-11-15 12:00", "https://khwebsc.com/account/password/forgot");

        Assert.DoesNotContain("<script>", message.HtmlBody);
        Assert.Contains("&lt;script&gt;", message.HtmlBody);
    }

    [Fact]
    public void Html_body_encodes_a_malicious_display_name()
    {
        const string hostile = "<script>alert('x')</script>\"&";

        var message = AccountEmailTemplates.EmailVerification("member@example.com", hostile, Link, TimeSpan.FromHours(24));

        Assert.DoesNotContain("<script>", message.HtmlBody);
        Assert.DoesNotContain("alert('x')", message.HtmlBody);
        Assert.Contains("&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;&quot;&amp;", message.HtmlBody);
    }

    [Fact]
    public void Html_body_encodes_the_link_so_its_query_cannot_break_the_attribute()
    {
        const string hostileLink = "https://khwebsc.com/account/verify-email?token=a\"><script>x</script>";

        var message = AccountEmailTemplates.PasswordReset("member@example.com", "小明", hostileLink, TimeSpan.FromHours(1));

        Assert.DoesNotContain("\"><script>", message.HtmlBody);
        Assert.Contains("token=a&quot;&gt;&lt;script&gt;x&lt;/script&gt;", message.HtmlBody);
    }

    [Fact]
    public void Html_body_turns_an_ampersand_in_the_link_into_an_entity()
    {
        var message = AccountEmailTemplates.EmailVerification("member@example.com", "小明", Link, TimeSpan.FromHours(24));

        Assert.Contains("token=abc&amp;lang=zh", message.HtmlBody);
    }

    [Fact]
    public void Plain_text_body_keeps_the_display_name_unescaped()
    {
        var message = AccountEmailTemplates.EmailVerification("member@example.com", "A&B", Link, TimeSpan.FromHours(24));

        Assert.Contains("A&B", message.TextBody);
        Assert.DoesNotContain("A&amp;B", message.TextBody);
    }

    [Fact]
    public void Blank_display_name_falls_back_to_a_generic_greeting()
    {
        var message = AccountEmailTemplates.EmailVerification("member@example.com", "   ", Link, TimeSpan.FromHours(24));

        Assert.Contains("會員", message.TextBody);
        Assert.Contains("會員", message.HtmlBody);
    }

    [Fact]
    public void Subject_never_contains_the_display_name()
    {
        var message = AccountEmailTemplates.PasswordReset("member@example.com", "小明超人", Link, TimeSpan.FromHours(1));

        Assert.DoesNotContain("小明超人", message.Subject);
    }
}
