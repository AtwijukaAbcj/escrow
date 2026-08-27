using System.Threading.Tasks;

namespace TrustPay.Auth.Application.Interfaces
{
    public interface IUnitOfWork
    {
        Task SaveChangesAsync();
    }
}
