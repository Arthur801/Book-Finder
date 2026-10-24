using Book_Finder.Application.Catalog;
using Book_Finder.Domain.Entities;

namespace UnitTests;

public sealed class BookBrowseServiceTests
{
    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(int.MinValue)]
    public async Task Page_below_one_is_treated_as_page_one(int page)
    {
        var port = new FakeBookBrowse();
        var service = new BookBrowseService(port);

        await service.ListAsync(page, CancellationToken.None);

        Assert.Equal(1, port.LastPage);
    }

    [Theory]
    [InlineData(1)]
    [InlineData(5)]
    [InlineData(int.MaxValue)]
    public async Task Positive_page_reaches_the_port_unchanged(int page)
    {
        var port = new FakeBookBrowse();
        var service = new BookBrowseService(port);

        await service.ListAsync(page, CancellationToken.None);

        Assert.Equal(page, port.LastPage);
    }

    [Fact]
    public async Task Port_receives_the_page_size_of_twenty()
    {
        var port = new FakeBookBrowse();
        var service = new BookBrowseService(port);

        await service.ListAsync(2, CancellationToken.None);

        Assert.Equal(20, port.LastPageSize);
        Assert.Equal(BookBrowseService.PageSize, port.LastPageSize);
    }

    [Fact]
    public async Task List_result_is_returned_unchanged()
    {
        var item = new BookBrowseItem(Guid.NewGuid(), "三體", ["劉慈欣"], "重慶出版社", new DateOnly(2008, 1, 1),
            PublishedDatePrecision.Month, null);
        var expected = new BookBrowsePage([item], 21, 1, BookBrowseService.PageSize);
        var service = new BookBrowseService(new FakeBookBrowse(listResult: expected));

        var result = await service.ListAsync(1, CancellationToken.None);

        Assert.Equal(expected, result);
    }

    [Fact]
    public async Task Home_sample_asks_the_port_for_ten_books()
    {
        var port = new FakeBookBrowse();
        var service = new BookBrowseService(port);

        var items = await service.SampleHomeAsync(CancellationToken.None);

        Assert.Equal(BookBrowseService.HomeSampleCount, port.LastSampleCount);
        Assert.Equal(10, BookBrowseService.HomeSampleCount);
        Assert.Empty(items);
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
        var page = new BookBrowsePage([], totalCount, 1, BookBrowseService.PageSize);

        Assert.Equal(expectedPages, page.TotalPages);
    }

    private sealed class FakeBookBrowse(BookBrowsePage? listResult = null) : IBookBrowse
    {
        public int LastPage { get; private set; }
        public int LastPageSize { get; private set; }
        public int LastSampleCount { get; private set; }

        public Task<BookBrowsePage> ListAsync(int page, int pageSize, CancellationToken cancellationToken)
        {
            LastPage = page;
            LastPageSize = pageSize;
            return Task.FromResult(listResult ?? new BookBrowsePage([], 0, page, pageSize));
        }

        public Task<IReadOnlyList<BookBrowseItem>> SampleAsync(int count, CancellationToken cancellationToken)
        {
            LastSampleCount = count;
            return Task.FromResult<IReadOnlyList<BookBrowseItem>>([]);
        }
    }
}
