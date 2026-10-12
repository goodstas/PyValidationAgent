using DemoShop.Data;

namespace DemoShop.Services;

public sealed class OrderSummaryService
{
    private readonly ICustomerRepository _customers;

    public OrderSummaryService(ICustomerRepository customers)
    {
        _customers = customers;
    }

    public async Task<IReadOnlyList<OrderSummary>> BuildSummariesAsync(IEnumerable<Order> orders)
    {
        var summaries = new List<OrderSummary>();
        foreach (var order in orders)
        {
            var customer = await _customers.GetByIdAsync(order.CustomerId);
            summaries.Add(new OrderSummary(order.Id, customer?.Name ?? "unknown", order.Lines.Count));
        }

        return summaries;
    }

    public async Task<IReadOnlyList<OrderSummary>> BuildSummariesBatchedAsync(IReadOnlyList<Order> orders)
    {
        var customers = await _customers.GetByIdsAsync(orders.Select(o => o.CustomerId).Distinct());
        var names = customers.ToDictionary(c => c.Id, c => c.Name);
        var summaries = new List<OrderSummary>();
        foreach (var order in orders)
        {
            names.TryGetValue(order.CustomerId, out var name);
            summaries.Add(new OrderSummary(order.Id, name ?? "unknown", order.Lines.Count));
        }

        return summaries;
    }
}
