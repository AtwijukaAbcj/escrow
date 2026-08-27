namespace TrustPay.Auth.Common.Interfaces
{
    public interface ITokenHashProvider
    {
        string Hash(string token);
        bool Verify(string token, string hash);
    }
}
