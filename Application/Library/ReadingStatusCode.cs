using Book_Finder.Domain.Entities;

namespace Book_Finder.Application.Library;

// Reading Status <-> code and label conversions (user-library.md §3, §4). The codes are the API and query-string
// contract, so they are spelled out here instead of derived from the enum or from Infrastructure's storage mapping.
public static class ReadingStatusCode
{
    public static string ToCode(ReadingStatus status) => status switch
    {
        ReadingStatus.WantToRead => "WANT_TO_READ",
        ReadingStatus.Reading => "READING",
        ReadingStatus.Finished => "FINISHED",
        _ => throw new ArgumentOutOfRangeException(nameof(status), status, null),
    };

    // Exact, case-sensitive match of the three codes only. Numbers and enum names are not accepted.
    public static bool TryParse(string? code, out ReadingStatus status)
    {
        switch (code)
        {
            case "WANT_TO_READ":
                status = ReadingStatus.WantToRead;
                return true;

            case "READING":
                status = ReadingStatus.Reading;
                return true;

            case "FINISHED":
                status = ReadingStatus.Finished;
                return true;

            default:
                status = default;
                return false;
        }
    }

    public static string Label(ReadingStatus status) => status switch
    {
        ReadingStatus.WantToRead => "想讀",
        ReadingStatus.Reading => "閱讀中",
        ReadingStatus.Finished => "已讀",
        _ => throw new ArgumentOutOfRangeException(nameof(status), status, null),
    };
}
