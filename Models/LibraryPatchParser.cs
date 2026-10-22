using System.Text.Json;
using Book_Finder.Application.Library;
using Book_Finder.Domain.Entities;

namespace Book_Finder.Models;

// Turns the PATCH /api/library/{bookId} body into a LibraryChange (api-spec.md §4). Only this file knows JsonElement.
// Plain model binding cannot tell "omitted" from "null", so the body is read property by property.
public static class LibraryPatchParser
{
    private const string WholeBodyMessage = "輸入資料有誤";
    private const string StatusMessage = "閱讀狀態必須是 WANT_TO_READ、READING 或 FINISHED";
    private const string RatingMessage = "評分必須介於 1 到 5";

    // Error keys are the camelCase field names; the whole-body error uses the empty key.
    public static LibraryPatchParseResult Parse(JsonElement? body)
    {
        if (body is not JsonElement element || element.ValueKind != JsonValueKind.Object)
            return new LibraryPatchParseResult.Invalid(new Dictionary<string, string> { [""] = WholeBodyMessage });

        var errors = new Dictionary<string, string>();

        ReadingStatus? status = null;
        if (element.TryGetProperty("readingStatus", out var statusElement))
        {
            // Only JSON strings holding one of the three exact codes count. JSON null, numbers and other types are errors.
            if (statusElement.ValueKind == JsonValueKind.String && ReadingStatusCode.TryParse(statusElement.GetString(), out var parsed))
                status = parsed;
            else
                errors["readingStatus"] = StatusMessage;
        }

        RatingChange rating = new RatingChange.Unchanged();
        if (element.TryGetProperty("rating", out var ratingElement))
        {
            if (ratingElement.ValueKind == JsonValueKind.Null)
            {
                rating = new RatingChange.Clear();
            }
            // TryGetInt32 accepts integer literals only, so 3.5 and 3.0 are rejected. It throws for non-number kinds
            // (strings, booleans, objects, arrays) instead of returning false, so the Number check must come first.
            else if (ratingElement.ValueKind == JsonValueKind.Number && ratingElement.TryGetInt32(out var value) && value is >= 1 and <= 5)
            {
                rating = new RatingChange.Set((short)value);
            }
            else
            {
                errors["rating"] = RatingMessage;
            }
        }

        if (errors.Count > 0)
            return new LibraryPatchParseResult.Invalid(errors);

        return new LibraryPatchParseResult.Valid(new LibraryChange(status, rating));
    }
}

// Each outcome is its own type, so callers pattern-match on it (same style as AddToLibraryResult).
public abstract record LibraryPatchParseResult
{
    public sealed record Valid(LibraryChange Change) : LibraryPatchParseResult;

    public sealed record Invalid(IReadOnlyDictionary<string, string> Errors) : LibraryPatchParseResult;
}
