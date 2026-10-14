namespace DemoShop.Data;

public sealed class InMemoryCustomerRepository : ICustomerRepository
{
    private readonly IReadOnlyDictionary<int, Customer> _customers = new Dictionary<int, Customer>
    {
        [1] = new Customer(1, "Ada", "ada@example.test"),
        [2] = new Customer(2, "Grace", "grace@example.test"),
    };

    public Task<Customer?> GetByIdAsync(int id) =>
        Task.FromResult(_customers.TryGetValue(id, out var customer) ? customer : null);

    public Task<IReadOnlyList<Customer>> GetByIdsAsync(IEnumerable<int> ids)
    {
        var wanted = ids.ToHashSet();
        IReadOnlyList<Customer> found = _customers.Values.Where(c => wanted.Contains(c.Id)).ToList();
        return Task.FromResult(found);
    }
}
