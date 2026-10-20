using Book_Finder.Application.Identity;

namespace UnitTests;

public sealed class AccountInputRulesTests
{
    private const string ValidEmail = "user@example.com";
    private const string ValidPassword = "password1";
    private const string ValidName = "Arthur";

    [Fact]
    public void Password_of_seven_characters_is_rejected()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, new string('a', 7), ValidName);

        Assert.False(result.IsValid);
        Assert.Equal("密碼長度須為 8～40 碼", result.Errors["password"]);
    }

    [Fact]
    public void Password_of_eight_characters_is_accepted()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, new string('a', 8), ValidName);

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Password_of_forty_characters_is_accepted()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, new string('a', 40), ValidName);

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Password_of_forty_one_characters_is_rejected()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, new string('a', 41), ValidName);

        Assert.False(result.IsValid);
        Assert.Equal("密碼長度須為 8～40 碼", result.Errors["password"]);
    }

    [Fact]
    public void Password_is_not_trimmed_so_surrounding_spaces_count_toward_length()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, " " + new string('a', 6) + " ", ValidName);

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Missing_password_reports_required_message()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, null, ValidName);

        Assert.Equal("請輸入密碼", result.Errors["password"]);
    }

    [Fact]
    public void Email_is_trimmed_and_keeps_its_original_case()
    {
        var result = AccountInputRules.ValidateRegistration(" A@X.com ", ValidPassword, ValidName);

        Assert.True(result.IsValid);
        Assert.Equal("A@X.com", result.Email);
    }

    [Fact]
    public void Blank_email_reports_required_message()
    {
        var result = AccountInputRules.ValidateRegistration("   ", ValidPassword, ValidName);

        Assert.Equal("請輸入 email", result.Errors["email"]);
    }

    [Fact]
    public void Malformed_email_reports_format_message()
    {
        var result = AccountInputRules.ValidateRegistration("not-an-email", ValidPassword, ValidName);

        Assert.False(result.IsValid);
        Assert.Equal("email 格式不正確", result.Errors["email"]);
    }

    [Fact]
    public void Email_of_321_characters_is_rejected_as_too_long()
    {
        var email = new string('a', 315) + "@x.com";
        Assert.Equal(321, email.Length);

        var result = AccountInputRules.ValidateRegistration(email, ValidPassword, ValidName);

        Assert.False(result.IsValid);
        Assert.Equal("email 最多 320 字元", result.Errors["email"]);
    }

    [Fact]
    public void Email_length_is_checked_after_trimming()
    {
        var email = " " + new string('a', 315) + "@x.com ";

        var result = AccountInputRules.ValidateRegistration(email, ValidPassword, ValidName);

        Assert.Equal("email 最多 320 字元", result.Errors["email"]);
        Assert.Equal(new string('a', 315) + "@x.com", result.Email);
    }

    [Fact]
    public void Email_of_320_characters_does_not_report_a_length_error()
    {
        var email = new string('a', 314) + "@x.com";
        Assert.Equal(320, email.Length);

        var result = AccountInputRules.ValidateRegistration(email, ValidPassword, ValidName);

        Assert.False(result.Errors.TryGetValue("email", out var message) && message == "email 最多 320 字元");
    }

    [Fact]
    public void Display_name_is_trimmed()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, "  Arthur  ");

        Assert.True(result.IsValid);
        Assert.Equal("Arthur", result.DisplayName);
    }

    [Fact]
    public void Display_name_of_only_whitespace_reports_required_message()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, "   \t ");

        Assert.False(result.IsValid);
        Assert.Equal("請輸入顯示名稱", result.Errors["displayName"]);
    }

    [Fact]
    public void Missing_display_name_reports_required_message()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, null);

        Assert.Equal("請輸入顯示名稱", result.Errors["displayName"]);
    }

    [Fact]
    public void Display_name_of_100_chinese_characters_is_accepted()
    {
        var name = new string('書', 100);

        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, name);

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Display_name_of_101_chinese_characters_is_rejected()
    {
        var name = new string('書', 101);

        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, name);

        Assert.False(result.IsValid);
        Assert.Equal("顯示名稱最多 100 字", result.Errors["displayName"]);
    }

    [Fact]
    public void Display_name_of_100_emoji_is_accepted_because_each_emoji_is_one_code_point()
    {
        var name = string.Concat(Enumerable.Repeat("😀", 100));
        Assert.Equal(200, name.Length);

        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, name);

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Display_name_of_101_emoji_is_rejected()
    {
        var name = string.Concat(Enumerable.Repeat("😀", 101));

        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, name);

        Assert.Equal("顯示名稱最多 100 字", result.Errors["displayName"]);
    }

    [Fact]
    public void When_all_fields_are_invalid_each_field_reports_its_own_error()
    {
        var result = AccountInputRules.ValidateRegistration("not-an-email", "short", "   ");

        Assert.False(result.IsValid);
        Assert.Equal(3, result.Errors.Count);
        Assert.Contains("email", result.Errors.Keys);
        Assert.Contains("password", result.Errors.Keys);
        Assert.Contains("displayName", result.Errors.Keys);
    }

    [Fact]
    public void Valid_registration_has_no_errors()
    {
        var result = AccountInputRules.ValidateRegistration(ValidEmail, ValidPassword, ValidName);

        Assert.True(result.IsValid);
        Assert.Empty(result.Errors);
    }

    [Fact]
    public void Login_with_seven_character_password_is_not_rejected()
    {
        var result = AccountInputRules.ValidateLogin(ValidEmail, new string('a', 7));

        Assert.True(result.IsValid);
        Assert.Empty(result.Errors);
    }

    [Fact]
    public void Login_with_empty_password_reports_required_message()
    {
        var result = AccountInputRules.ValidateLogin(ValidEmail, "");

        Assert.False(result.IsValid);
        Assert.Equal("請輸入密碼", result.Errors["password"]);
    }

    [Fact]
    public void Login_with_blank_email_reports_required_message()
    {
        var result = AccountInputRules.ValidateLogin("  ", ValidPassword);

        Assert.Equal("請輸入 email", result.Errors["email"]);
    }

    [Fact]
    public void Login_does_not_check_email_format()
    {
        var result = AccountInputRules.ValidateLogin("not-an-email", ValidPassword);

        Assert.True(result.IsValid);
    }

    [Fact]
    public void Login_trims_email_and_keeps_its_case()
    {
        var result = AccountInputRules.ValidateLogin(" A@X.com ", ValidPassword);

        Assert.Equal("A@X.com", result.Email);
    }
}
