using TrustPay.Auth.Domain.Entities;

namespace TrustPay.Auth.Application.Interfaces
{
    public interface ITokenService
    {
        string CreateToken(User user);
    }
}
