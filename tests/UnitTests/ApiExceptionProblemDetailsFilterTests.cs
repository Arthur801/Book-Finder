using Book_Finder.Application.Recommendation;
using Book_Finder.Infrastructure.Identity;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Abstractions;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.AspNetCore.Mvc.Infrastructure;
using Microsoft.AspNetCore.Routing;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace UnitTests;

public sealed class ApiExceptionProblemDetailsFilterTests
{
    [Fact]
    public void AI_unavailable_maps_to_502_and_is_not_logged_again_by_the_filter()
    {
        var (filter, logger) = Build();
        var context = Context("/api/recommendations", new AiUnavailableException("OpenAI 推薦排序失敗", new InvalidOperationException("sdk")));

        filter.OnException(context);

        Assert.True(context.ExceptionHandled);
        Assert.Equal(502, ((ObjectResult)context.Result!).StatusCode);
        Assert.Empty(logger.Entries);
    }

    [Fact]
    public void AI_timeout_maps_to_504_and_is_not_logged_again_by_the_filter()
    {
        var (filter, logger) = Build();
        var context = Context("/api/recommendations", new AiTimeoutException());

        filter.OnException(context);

        Assert.True(context.ExceptionHandled);
        Assert.Equal(504, ((ObjectResult)context.Result!).StatusCode);
        Assert.Empty(logger.Entries);
    }

    [Fact]
    public void Other_exceptions_map_to_500_and_are_logged_once_as_errors()
    {
        var (filter, logger) = Build();
        var error = new InvalidOperationException("boom");
        var context = Context("/api/recommendations", error);

        filter.OnException(context);

        Assert.True(context.ExceptionHandled);
        Assert.Equal(500, ((ObjectResult)context.Result!).StatusCode);
        var entry = Assert.Single(logger.Entries);
        Assert.Equal(LogLevel.Error, entry.Level);
        Assert.Same(error, entry.Exception);
    }

    private static (ApiExceptionProblemDetailsFilter Filter, RecordingLogger Logger) Build()
    {
        var logger = new RecordingLogger();
        var problemDetails = new DefaultProblemDetailsFactory(Options.Create(new ApiBehaviorOptions()));
        return (new ApiExceptionProblemDetailsFilter(problemDetails, logger), logger);
    }

    private static ExceptionContext Context(string path, Exception exception)
    {
        var http = new DefaultHttpContext();
        http.Request.Method = "POST";
        http.Request.Path = path;
        var actionContext = new ActionContext(http, new RouteData(), new ActionDescriptor());
        return new ExceptionContext(actionContext, []) { Exception = exception };
    }

    private sealed class RecordingLogger : ILogger<ApiExceptionProblemDetailsFilter>
    {
        public List<Entry> Entries { get; } = [];

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => true;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
            Entries.Add(new Entry(logLevel, exception));

        public sealed record Entry(LogLevel Level, Exception? Exception);
    }
}
