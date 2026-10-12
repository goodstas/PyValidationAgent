using System.Security.Cryptography;
using System.Text;

namespace DemoShop.Services;

public sealed class LegacyHasher
{
    public string FingerprintPassword(string password)
    {
        using var sha1 = SHA1.Create();
        byte[] digest = sha1.ComputeHash(Encoding.UTF8.GetBytes(password));
        return Convert.ToHexString(digest);
    }

    public string FingerprintDocument(string content)
    {
        using var sha256 = SHA256.Create();
        byte[] digest = sha256.ComputeHash(Encoding.UTF8.GetBytes(content));
        return Convert.ToHexString(digest);
    }
}
