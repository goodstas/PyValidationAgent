namespace DemoShop.Data;

public interface ICustomerRepository
{
    Task<Customer?> GetByIdAsync(int id);

    Task<IReadOnlyList<Customer>> GetByIdsAsync(IEnumerable<int> ids);
}
