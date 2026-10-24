using Book_Finder.Application.Catalog;

namespace UnitTests;

public sealed class Unicode151AssignedTests
{
    [Theory]
    [InlineData(0x0041)]
    [InlineData(0x0430)]
    [InlineData(0x1E030)] // added in Unicode 15.0
    [InlineData(0x0000)]
    [InlineData(0xE0001)] // LANGUAGE TAG, assigned since 3.1
    public void Assigned_code_points_are_contained(int codePoint) => Assert.True(Unicode151Assigned.Contains(codePoint));

    // Unicode 16.0 adds OUTLINED DIGITs at U+1CCF0..U+1CCF9; they are unassigned in 15.1 and must split NFKC runs.
    [Theory]
    [InlineData(0x1CCF0)]
    [InlineData(0x1CCF9)]
    [InlineData(0x0378)]
    [InlineData(0xE0080)]
    public void Unassigned_code_points_are_not_contained(int codePoint) => Assert.False(Unicode151Assigned.Contains(codePoint));
}
