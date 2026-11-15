using System.Text;
using Book_Finder.Application.Email;
using Book_Finder.Infrastructure.Email;
using Microsoft.Extensions.Time.Testing;

namespace UnitTests;

// Local development sender (Email:Provider Pickup): one .eml file per message in a directory. Tests use a fresh temp directory.
public sealed class PickupDirectoryEmailSenderTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "book-finder-pickup-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        if (Directory.Exists(directory))
            Directory.Delete(directory, recursive: true);
    }

    [Fact]
    public async Task Writes_one_file_per_message_into_the_directory()
    {
        var sender = CreateSender();

        await sender.SendAsync(new EmailMessage("a@example.com", "第一封", "text one", "<p>one</p>"), CancellationToken.None);
        await sender.SendAsync(new EmailMessage("b@example.com", "第二封", "text two", "<p>two</p>"), CancellationToken.None);

        var files = Directory.GetFiles(directory, "*.eml");
        Assert.Equal(2, files.Length);
    }

    [Fact]
    public async Task File_holds_the_headers_and_both_bodies_in_utf8()
    {
        var sender = CreateSender();

        await sender.SendAsync(new EmailMessage("member@example.com", "驗證信", "請點連結 https://khwebsc.com/x?token=t1", "<p>你好</p>"), CancellationToken.None);

        var content = ReadSingleFile();
        Assert.Contains("From: noreply@localhost", content);
        Assert.Contains("To: member@example.com", content);
        Assert.Contains("Subject: 驗證信", content);
        Assert.Contains("Content-Type: multipart/alternative", content);
        Assert.Contains("Content-Type: text/plain; charset=UTF-8", content);
        Assert.Contains("Content-Type: text/html; charset=UTF-8", content);
        Assert.Contains(Base64(Encoding.UTF8.GetBytes("請點連結 https://khwebsc.com/x?token=t1")), content.Replace("\r", "").Replace("\n", ""));
        Assert.Contains(Base64(Encoding.UTF8.GetBytes("<p>你好</p>")), content.Replace("\r", "").Replace("\n", ""));
    }

    [Fact]
    public async Task Creates_the_directory_when_it_is_missing()
    {
        Assert.False(Directory.Exists(directory));
        var sender = CreateSender();

        await sender.SendAsync(new EmailMessage("a@example.com", "s", "t", "<p>h</p>"), CancellationToken.None);

        Assert.Single(Directory.GetFiles(directory, "*.eml"));
    }

    [Fact]
    public async Task File_name_starts_with_the_send_time_so_files_sort_in_order()
    {
        var time = new FakeTimeProvider(new DateTimeOffset(2026, 11, 15, 8, 30, 15, 250, TimeSpan.Zero));
        var sender = new PickupDirectoryEmailSender(directory, "noreply@localhost", time);

        await sender.SendAsync(new EmailMessage("a@example.com", "s", "t", "<p>h</p>"), CancellationToken.None);

        var name = Path.GetFileName(Assert.Single(Directory.GetFiles(directory, "*.eml")));
        Assert.StartsWith("20261115T083015250-", name);
    }

    private PickupDirectoryEmailSender CreateSender() =>
        new(directory, "noreply@localhost", new FakeTimeProvider(DateTimeOffset.UtcNow));

    private string ReadSingleFile() => File.ReadAllText(Assert.Single(Directory.GetFiles(directory, "*.eml")), Encoding.UTF8);

    private static string Base64(byte[] bytes) => Convert.ToBase64String(bytes);
}
