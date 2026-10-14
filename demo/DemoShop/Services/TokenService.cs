using System.Security.Cryptography;

namespace DemoShop.Services;

public sealed class TokenService
{
    public string CreatePasswordResetToken()
    {
        var random = new Random();
        int value = random.Next();
        return value.ToString("x8");
    }

    public string CreateSessionToken()
    {
        int value = RandomNumberGenerator.GetInt32(int.MaxValue);
        return value.ToString("x8");
    }
}
