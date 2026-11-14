using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;
using Book_Finder.Mcp;
using Book_Finder.Mcp.Contracts;
using Book_Finder.Mcp.Services;
using Microsoft.Extensions.Options;

namespace UnitTests;

// The MCP search use case (plan mcp-server section 3.3). Blank input never reaches the port. Otherwise the port is asked for
// page 1 of up to 50 hits, and the result says how many matched in total and whether more exist beyond the returned list.
public sealed class McpBookSearchServiceTests
{
    private const string Base = "https://khwebsc.com";

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Blank_input_is_a_validation_error_and_never_calls_the_port(string? input)
    {
        var port = new FakeBookSearch();
        var service = Create(port);

        var result = await service.SearchAsync(input, CancellationToken.None);

        Assert.Equal(0, port.CallCount);
        var failed = Assert.IsType<McpBookSearchResult.ValidationFailed>(result);
        Assert.Equal("VALIDATION_FAILED", failed.Error.ErrorCode);
        Assert.Equal("query", failed.Error.Field);
        Assert.Equal("error", failed.Error.Status);
    }

    [Fact]
    public async Task Keyword_is_searched_as_page_one_of_fifty_results()
    {
        var port = new FakeBookSearch();
        var service = Create(port);

        await service.SearchAsync("  劉慈欣 ", CancellationToken.None);

        Assert.Equal(1, port.CallCount);
        Assert.Equal(1, port.LastPage);
        Assert.Equal(50, port.LastPageSize);
        Assert.Equal(new SearchQuery.Keyword("劉慈欣"), port.LastQuery);
    }

    [Fact]
    public async Task Isbn_input_reaches_the_port_as_an_isbn_query()
    {
        var port = new FakeBookSearch();
        var service = Create(port);

        await service.SearchAsync("978-986-1234-56-7", CancellationToken.None);

        Assert.Equal(new SearchQuery.Isbn("9789861234567", "978-986-1234-56-7"), port.LastQuery);
    }

    [Theory]
    [InlineData(0, 0, false)]
    [InlineData(1, 1, false)]
    [InlineData(49, 49, false)]
    [InlineData(50, 50, false)]
    [InlineData(51, 50, true)]
    [InlineData(100, 50, true)]
    public async Task Returned_count_and_has_more_follow_the_total(int totalCount, int expectedReturned, bool expectedHasMore)
    {
        var port = new FakeBookSearch { TotalCount = totalCount };
        var service = Create(port);

        var found = Assert.IsType<McpBookSearchResult.Found>(await service.SearchAsync("三體", CancellationToken.None)).Result;

        Assert.Equal(totalCount, found.TotalCount);
        Assert.Equal(expectedReturned, found.ReturnedCount);
        Assert.Equal(expectedReturned, found.Books.Count);
        Assert.Equal(expectedHasMore, found.HasMore);
        Assert.Equal("success", found.Status);
    }

    [Fact]
    public async Task Zero_matches_still_return_the_search_url_with_an_empty_book_list()
    {
        var service = Create(new FakeBookSearch { TotalCount = 0 });

        var found = Assert.IsType<McpBookSearchResult.Found>(await service.SearchAsync("沒有這本書", CancellationToken.None)).Result;

        Assert.Empty(found.Books);
        Assert.False(found.HasMore);
        Assert.Equal("https://khwebsc.com/search?q=%E6%B2%92%E6%9C%89%E9%80%99%E6%9C%AC%E6%9B%B8", found.SearchUrl);
        Assert.Equal("沒有這本書", found.Query);
    }

    [Fact]
    public async Task Each_book_maps_to_id_title_authors_and_its_book_url()
    {
        var id = Guid.Parse("5b0e6f2a-1f57-4a58-9a1c-2d3c4b5a6f70");
        var hit = new BookSearchHit(id, "三體", ["劉慈欣", "王晉康"], "重慶出版社", new DateOnly(2008, 1, 1),
            PublishedDatePrecision.Month, null);
        var service = Create(new FakeBookSearch { Hits = [hit], TotalCount = 1 });

        var found = Assert.IsType<McpBookSearchResult.Found>(await service.SearchAsync("三體", CancellationToken.None)).Result;

        var book = Assert.Single(found.Books);
        Assert.Equal(id, book.Id);
        Assert.Equal("三體", book.Title);
        Assert.Equal(["劉慈欣", "王晉康"], book.Authors);
        Assert.Equal("https://khwebsc.com/books/5b0e6f2a-1f57-4a58-9a1c-2d3c4b5a6f70", book.BookUrl);
    }

    private static McpBookSearchService Create(IBookSearch port) =>
        new(port, new McpUrlBuilder(Options.Create(new McpOptions { Enabled = true, PublicBaseUrl = Base })));

    // Returns the hits it is given, or min(TotalCount, pageSize) generated hits, as the real port does for page 1.
    private sealed class FakeBookSearch : IBookSearch
    {
        public int CallCount { get; private set; }
        public SearchQuery? LastQuery { get; private set; }
        public int LastPage { get; private set; }
        public int LastPageSize { get; private set; }
        public int TotalCount { get; init; }
        public IReadOnlyList<BookSearchHit>? Hits { get; init; }

        public Task<BookSearchPage> SearchAsync(SearchQuery query, int page, int pageSize, CancellationToken cancellationToken)
        {
            CallCount++;
            LastQuery = query;
            LastPage = page;
            LastPageSize = pageSize;

            var hits = Hits ?? Enumerable.Range(1, Math.Min(TotalCount, pageSize))
                .Select(i => new BookSearchHit(Guid.NewGuid(), $"書 {i}", ["作者"], null, null, null, null))
                .ToList();
            return Task.FromResult(new BookSearchPage(hits, TotalCount, page, pageSize));
        }
    }
}
