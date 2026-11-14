using Microsoft.Extensions.Logging;

namespace TestDoubles;

// Keeps every formatted log line so a test can assert on levels, messages and exceptions. Thread-safe: background workers log from other threads.
public sealed class RecordingLogger<T> : ILogger<T>
{
    private readonly object _gate = new();
    private readonly List<Entry> _entries = [];

    public IReadOnlyList<Entry> Entries
    {
        get
        {
            lock (_gate)
                return _entries.ToArray();
        }
    }

    public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

    public bool IsEnabled(LogLevel logLevel) => true;

    public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
    {
        lock (_gate)
            _entries.Add(new Entry(logLevel, formatter(state, exception), exception));
    }

    public sealed record Entry(LogLevel Level, string Message, Exception? Exception);
}
