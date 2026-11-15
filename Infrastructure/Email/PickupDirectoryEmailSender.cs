using System.Globalization;
using System.Text;
using Book_Finder.Application.Email;

namespace Book_Finder.Infrastructure.Email;

// Local development adapter (Email:Provider Pickup, plan member-center C1). Each message becomes one .eml file in the directory, as a
// multipart/alternative mail that a mail client can open. The subject is written as raw UTF-8, which is enough for local reading.
// Never configure this in production: the mail would only land on disk.
public sealed class PickupDirectoryEmailSender(string directory, string from, TimeProvider time) : IEmailSender
{
    public async Task SendAsync(EmailMessage message, CancellationToken ct)
    {
        Directory.CreateDirectory(directory);

        var now = time.GetUtcNow();
        var path = Path.Combine(directory, $"{now.UtcDateTime:yyyyMMddTHHmmssfff}-{Guid.NewGuid():N}.eml");
        var boundary = "book-finder-" + Guid.NewGuid().ToString("N");

        var eml = new StringBuilder();
        eml.Append("Date: ").Append(now.ToString("ddd, dd MMM yyyy HH:mm:ss +0000", CultureInfo.InvariantCulture)).Append("\r\n");
        eml.Append("From: ").Append(from).Append("\r\n");
        eml.Append("To: ").Append(message.To).Append("\r\n");
        eml.Append("Subject: ").Append(message.Subject).Append("\r\n");
        eml.Append("MIME-Version: 1.0\r\n");
        eml.Append("Content-Type: multipart/alternative; boundary=\"").Append(boundary).Append("\"\r\n\r\n");
        AppendPart(eml, boundary, "text/plain", message.TextBody);
        AppendPart(eml, boundary, "text/html", message.HtmlBody);
        eml.Append("--").Append(boundary).Append("--\r\n");

        await File.WriteAllTextAsync(path, eml.ToString(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false), ct);
    }

    // Bodies are base64 so line breaks, quotes and non-ASCII text survive any mail reader unchanged.
    private static void AppendPart(StringBuilder eml, string boundary, string contentType, string body)
    {
        eml.Append("--").Append(boundary).Append("\r\n");
        eml.Append("Content-Type: ").Append(contentType).Append("; charset=UTF-8\r\n");
        eml.Append("Content-Transfer-Encoding: base64\r\n\r\n");
        eml.Append(Convert.ToBase64String(Encoding.UTF8.GetBytes(body), Base64FormattingOptions.InsertLineBreaks)).Append("\r\n");
    }
}
