namespace Book_Finder.Application.Recommendation;

// Truncates by Unicode code points, not UTF-16 units, so a surrogate pair is never split.
public static class CodePoints
{
    public static string? Truncate(string? text, int maxCodePoints)
    {
        // A negative limit has no meaning here, and the loop below would silently return the full text.
        ArgumentOutOfRangeException.ThrowIfNegative(maxCodePoints);

        if (text is null)
            return null;

        var count = 0;
        var offset = 0;
        foreach (var rune in text.EnumerateRunes())
        {
            if (count == maxCodePoints)
                return text[..offset];

            count++;
            offset += rune.Utf16SequenceLength;
        }

        return text;
    }
}
