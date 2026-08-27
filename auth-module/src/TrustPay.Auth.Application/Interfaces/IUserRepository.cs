using System.Threading.Tasks;
using TrustPay.Auth.Domain.Entities;
using TrustPay.Auth.Domain.ValueObjects;

namespace TrustPay.Auth.Application.Interfaces
{
    public interface IUserRepository
    {
        Task<User?> FindByEmailAsync(EmailAddress email);
        Task<User?> FindByIdAsync(UserId id);
        Task AddAsync(User user);
    }
}
