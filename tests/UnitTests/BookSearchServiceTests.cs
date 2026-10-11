using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;

namespace UnitTests;

public sealed class BookSearchServiceTests
{
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public async Task Empty_input_never_calls_the_port_and_returns_an_empty_page(string? input)
    {
        var port = new FakeBookSearch();
        var service = new BookSearchService(port);

        var result = await service.SearchAsync(input, 3, CancellationToken.None);

        Assert.Equal(0, port.CallCount);
        Assert.Empty(result.Hits);
        Assert.Equal(0, result.TotalCount);
        Assert.Equal(3, result.Page);
        Assert.Equal(BookSearchService.PageSize, result.PageSize);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-3)]
    public async Task Page_below_one_is_treated_as_page_one(int page)
    {
        var port = new FakeBookSearch();
        var service = new BookSearchService(port);

        var result = await service.SearchAsync("三體", page, CancellationToken.None);

        Assert.Equal(1, port.LastPage);
        Assert.Equal(1, result.Page);
    }

    [Fact]
    public async Task Port_receives_the_page_size_of_twenty()
    {
        var port = new FakeBookSearch();
        var service = new BookSearchService(port);

        await service.SearchAsync("三體", 2, CancellationToken.None);

        Assert.Equal(20, port.LastPageSize);
        Assert.Equal(BookSearchService.PageSize, port.LastPageSize);
        Assert.Equal(2, port.LastPage);
    }

    [Fact]
    public async Task Parsed_isbn_query_reaches_the_port()
    {
        var port = new FakeBookSearch();
        var service = new BookSearchService(port);

        await service.SearchAsync(" 978-986-1234-56-7 ", 1, CancellationToken.None);

        Assert.Equal(new SearchQuery.Isbn("9789861234567"), port.LastQuery);
    }

    [Fact]
    public async Task Parsed_keyword_query_reaches_the_port()
    {
        var port = new FakeBookSearch();
        var service = new BookSearchService(port);

        await service.SearchAsync("  劉慈欣 ", 1, CancellationToken.None);

        Assert.Equal(new SearchQuery.Keyword("劉慈欣"), port.LastQuery);
    }

    [Fact]
    public async Task Port_result_is_returned_unchanged()
    {
        var hit = new BookSearchHit(Guid.NewGuid(), "三體", ["劉慈欣"], "重慶出版社", new DateOnly(2008, 1, 1),
            PublishedDatePrecision.Month, null);
        var expected = new BookSearchPage([hit], 21, 1, BookSearchService.PageSize);
        var service = new BookSearchService(new FakeBookSearch(expected));

        var result = await service.SearchAsync("三體", 1, CancellationToken.None);

        Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData(0, 0)]
    [InlineData(1, 1)]
    [InlineData(20, 1)]
    [InlineData(21, 2)]
    [InlineData(40, 2)]
    [InlineData(41, 3)]
    public void Total_pages_is_the_ceiling_of_total_count_over_page_size(int totalCount, int expectedPages)
    {
        var page = new BookSearchPage([], totalCount, 1, BookSearchService.PageSize);

        Assert.Equal(expectedPages, page.TotalPages);
    }

    private sealed class FakeBookSearch(BookSearchPage? result = null) : IBookSearch
    {
        public int CallCount { get; private set; }
        public SearchQuery? LastQuery { get; private set; }
        public int LastPage { get; private set; }
        public int LastPageSize { get; private set; }

        public Task<BookSearchPage> SearchAsync(SearchQuery query, int page, int pageSize, CancellationToken cancellationToken)
        {
            CallCount++;
            LastQuery = query;
            LastPage = page;
            LastPageSize = pageSize;
            return Task.FromResult(result ?? new BookSearchPage([], 0, page, pageSize));
        }
    }
}
