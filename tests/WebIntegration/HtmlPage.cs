using System.Net;
using System.Text.RegularExpressions;

namespace WebIntegration;

// Helpers for pages rendered over HTTP: fetching them and reading the bestseller list back out of the HTML.
internal static partial class HtmlPage
{
    // Ranks in the order the page rendered them (one data-rank attribute per bestseller entry).
    public static IReadOnlyList<int> RenderedRanks(string html) =>
        DataRank().Matches(html).Select(match => int.Parse(match.Groups[1].Value)).ToList();

    // Asserts 200 and returns the decoded HTML: Razor escapes CJK text as numeric entities (&#x4E09;), which browsers display as-is.
    public static async Task<string> GetPageAsync(this HttpClient client, string url)
    {
        var response = await client.GetAsync(url);
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        return WebUtility.HtmlDecode(await response.Content.ReadAsStringAsync());
    }

    [GeneratedRegex("data-rank=\"(\\d+)\"")]
    private static partial Regex DataRank();
}
