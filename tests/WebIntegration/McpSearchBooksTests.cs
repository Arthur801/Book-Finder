using System.Net;
using System.Text.Json;
using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;

namespace WebIntegration;

// search_books over real HTTP (plan mcp-server section 3.3, MCP-101). Anonymous, no token needed. The results come from the same
// Local Database and order as the website search, and the 50-hit limit is checked on the wire.
[Collection(WebCollection.Name)]
public sealed class McpSearchBooksTests(WebFixture fixture)
{
    private const string Query = "心理學";

    private static readonly WebApplicationFactoryClientOptions ClientOptions = new()
    {
        BaseAddress = new Uri("https://localhost"),
        AllowAutoRedirect = false,
    };

    [Fact]
    public async Task Anonymous_call_with_no_matches_returns_empty_books_and_the_search_url()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = "不存在的書名" }));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = StructuredOf(await McpWire.ReadRpcAsync(response));
        Assert.Equal("success", result.GetProperty("status").GetString());
        Assert.Equal(0, result.GetProperty("totalCount").GetInt32());
        Assert.Equal(0, result.GetProperty("returnedCount").GetInt32());
        Assert.False(result.GetProperty("hasMore").GetBoolean());
        Assert.Equal(0, result.GetProperty("books").GetArrayLength());
        Assert.Equal("https://khwebsc.com/search?q=%E4%B8%8D%E5%AD%98%E5%9C%A8%E7%9A%84%E6%9B%B8%E5%90%8D", result.GetProperty("searchUrl").GetString());
    }

    [Fact]
    public async Task Fifty_one_matches_return_fifty_books_with_the_true_total_and_has_more()
    {
        await fixture.ResetDatabaseAsync();
        await SeedBooksAsync(51);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = Query }));

        var result = StructuredOf(await McpWire.ReadRpcAsync(response));
        Assert.Equal(51, result.GetProperty("totalCount").GetInt32());
        Assert.Equal(50, result.GetProperty("returnedCount").GetInt32());
        Assert.Equal(50, result.GetProperty("books").GetArrayLength());
        Assert.True(result.GetProperty("hasMore").GetBoolean());
    }

    [Fact]
    public async Task Book_order_matches_the_first_page_of_the_website_search()
    {
        await fixture.ResetDatabaseAsync();
        await SeedBooksAsync(30);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = Query }));

        var mcpIds = StructuredOf(await McpWire.ReadRpcAsync(response)).GetProperty("books").EnumerateArray()
            .Select(book => book.GetProperty("id").GetGuid()).ToList();
        using var scope = app.Services.CreateScope();
        var website = await scope.ServiceProvider.GetRequiredService<BookSearchService>()
            .SearchAsync(Query, 1, CancellationToken.None);
        var websiteIds = website.Hits.Select(hit => hit.BookId).ToList();
        Assert.Equal(30, mcpIds.Count);
        Assert.Equal(20, websiteIds.Count);
        Assert.Equal(websiteIds, mcpIds.Take(websiteIds.Count));
    }

    [Fact]
    public async Task Each_book_has_id_title_authors_and_a_book_url()
    {
        await fixture.ResetDatabaseAsync();
        var books = await CatalogSeed.AddBooksAsync(fixture,
        [
            new BookSeed("心理學入門")
            {
                Contributors = [new ContributorSeed(1, "甲作者", ContributorRole.Author), new ContributorSeed(2, "乙作者", ContributorRole.Author)],
            },
        ]);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = Query }));

        var book = StructuredOf(await McpWire.ReadRpcAsync(response)).GetProperty("books")[0];
        Assert.Equal(books[0].BookId, book.GetProperty("id").GetGuid());
        Assert.Equal("心理學入門", book.GetProperty("title").GetString());
        Assert.Equal(["甲作者", "乙作者"], book.GetProperty("authors").EnumerateArray().Select(a => a.GetString()));
        Assert.Equal($"https://khwebsc.com/books/{books[0].BookId:D}", book.GetProperty("bookUrl").GetString());
    }

    [Fact]
    public async Task Blank_query_is_a_tool_error_with_validation_failed()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = "   " }));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var rpc = await McpWire.ReadRpcAsync(response);
        var result = rpc.GetProperty("result");
        Assert.True(result.GetProperty("isError").GetBoolean());
        var error = StructuredOf(rpc);
        Assert.Equal("error", error.GetProperty("status").GetString());
        Assert.Equal("VALIDATION_FAILED", error.GetProperty("errorCode").GetString());
        Assert.Equal("query", error.GetProperty("field").GetString());
    }

    [Fact]
    public async Task Anonymous_call_gets_the_result_without_any_cookie_or_token()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = Query }));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.False(response.Headers.Contains("Set-Cookie"));
    }

    [Fact]
    public async Task Invalid_bearer_token_is_refused_with_401_even_for_search()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);
        var badToken = "not-an-access-token";

        var response = await McpWire.PostAsync(client, McpWire.ToolsCall("search_books", arguments: new { query = Query }), bearer: badToken);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Protocol_2026_07_28_call_with_method_and_name_headers_returns_the_structured_result()
    {
        await fixture.ResetDatabaseAsync();
        await SeedBooksAsync(2);
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(
            client,
            McpWire.ToolsCall("search_books", protocolVersion: McpWire.NewProtocolVersion, arguments: new { query = Query }),
            protocolVersion: McpWire.NewProtocolVersion,
            mcpName: "search_books");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = StructuredOf(await McpWire.ReadRpcAsync(response));
        Assert.Equal(2, result.GetProperty("totalCount").GetInt32());
    }

    // Contract snapshot: the name and input schema clients build their calls from (plan section 3.3).
    [Fact]
    public async Task tools_list_describes_search_books_with_a_required_string_query()
    {
        await fixture.ResetDatabaseAsync();
        await using var app = CreateFactory();
        var client = app.CreateClient(ClientOptions);

        var response = await McpWire.PostAsync(client, McpWire.ToolsList());

        var tools = (await McpWire.ReadRpcAsync(response)).GetProperty("result").GetProperty("tools").EnumerateArray().ToList();
        var search = Assert.Single(tools, tool => tool.GetProperty("name").GetString() == "search_books");
        var schema = search.GetProperty("inputSchema");
        Assert.Equal("object", schema.GetProperty("type").GetString());
        Assert.Equal(["query"], schema.GetProperty("required").EnumerateArray().Select(v => v.GetString()));
        Assert.Equal("string", schema.GetProperty("properties").GetProperty("query").GetProperty("type").GetString());
        Assert.Contains("50", search.GetProperty("description").GetString());
    }

    private BookFinderFactory CreateFactory()
    {
        var app = fixture.CreateFactory();
        app.McpEnabled = true;
        return app;
    }

    // Seeds n books whose titles contain the query. Dates vary so the order is not simply by id, which checks the website ordering too.
    private async Task SeedBooksAsync(int count) =>
        await CatalogSeed.AddBooksAsync(fixture, Enumerable.Range(1, count).Select(i => new BookSeed($"心理學 {i:D2}")
        {
            PublishedDate = i % 3 == 0 ? null : new DateOnly(2000 + i % 7, 1 + i % 12, 1),
            PublishedDatePrecision = i % 3 == 0 ? null : PublishedDatePrecision.Month,
        }));

    private static JsonElement StructuredOf(JsonElement rpc) => rpc.GetProperty("result").GetProperty("structuredContent");
}
