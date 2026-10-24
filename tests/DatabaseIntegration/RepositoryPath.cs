namespace DatabaseIntegration;

// Locates files that live in the repository (deploy/, Docs/) from the test binary, which runs in bin/ under the test project.
internal static class RepositoryPath
{
    public static string Resolve(params string[] parts)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "Book-Finder.slnx")))
            dir = dir.Parent;
        if (dir is null)
            throw new InvalidOperationException("Repository root (Book-Finder.slnx) not found above the test binary.");
        return Path.Combine([dir.FullName, .. parts]);
    }
}
