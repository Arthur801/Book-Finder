using System.Security.Cryptography;
using System.Text;

namespace Book_Finder.Application.Recommendation;

// SHA-256 over the UTF-8 bytes of a generated text, as 64 lowercase hex characters.
// Used for embedding and profile source hashes, so the output must stay stable across releases.
internal static class ContentHash
{
    public static string Sha256Hex(string text)
    {
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    }
}
