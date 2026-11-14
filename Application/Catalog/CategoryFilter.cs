namespace Book_Finder.Application.Catalog;

// One Canonical Category as the browse sidebar shows it. BookCount already honours the current source filter.
public sealed record CategorySummary(Guid Id, string Slug, string DisplayName, int BookCount);

// One source offered in the source filter. Code is the SourceProvider.Code used in URLs.
public sealed record SourceOption(string Code, string DisplayName);
