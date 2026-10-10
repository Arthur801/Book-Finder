using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace Book_Finder.Infrastructure.Persistence;

// Enums are stored as UPPER_SNAKE strings ("WantToRead" → "WANT_TO_READ"), the vocabulary the
// data model and the Python crawler use. CHECK constraints are generated from the same mapping.
internal static class StoredEnum
{
    public static string ToStored<T>(T value) where T : struct, Enum => SnakeCase.Upper(value.ToString());

    public static T FromStored<T>(string stored) where T : struct, Enum =>
        Lookup<T>.ByStored.TryGetValue(stored, out var value)
            ? value
            : throw new InvalidOperationException($"'{stored}' is not a stored {typeof(T).Name} value.");

    // "column IN ('A', 'B')" over the given values, or over every value when none are given.
    public static string InSql<T>(string column, params T[] values) where T : struct, Enum =>
        $"{column} IN ({string.Join(", ", (values.Length > 0 ? values : Enum.GetValues<T>()).Select(v => $"'{ToStored(v)}'"))})";

    public static PropertyBuilder<T> HasStoredEnumConversion<T>(this PropertyBuilder<T> property) where T : struct, Enum =>
        property.HasConversion(Converter<T>());

    public static PropertyBuilder<T?> HasStoredEnumConversion<T>(this PropertyBuilder<T?> property) where T : struct, Enum =>
        property.HasConversion(Converter<T>());

    private static ValueConverter<T, string> Converter<T>() where T : struct, Enum =>
        new(v => ToStored(v), s => FromStored<T>(s));

    private static class Lookup<T> where T : struct, Enum
    {
        public static readonly Dictionary<string, T> ByStored = Enum.GetValues<T>().ToDictionary(v => ToStored(v));
    }
}
