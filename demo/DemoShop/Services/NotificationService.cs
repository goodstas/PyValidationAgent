namespace DemoShop.Services;

public interface INotificationSender
{
    Task SendAsync(string recipient, string message);
}

public sealed class LoggingNotificationSender : INotificationSender
{
    private readonly ILogger<LoggingNotificationSender> _logger;

    public LoggingNotificationSender(ILogger<LoggingNotificationSender> logger)
    {
        _logger = logger;
    }

    public Task SendAsync(string recipient, string message)
    {
        _logger.LogInformation("Notify {Recipient}: {Message}", recipient, message);
        return Task.CompletedTask;
    }
}

public sealed class NotificationService
{
    private readonly INotificationSender _sender;

    public NotificationService(INotificationSender sender)
    {
        _sender = sender;
    }

    public Task NotifyAllAsync(IReadOnlyList<string> recipients, string message)
    {
        return Task.WhenAll(recipients.Select(recipient => _sender.SendAsync(recipient, message)));
    }

    public async Task NotifyInBatchesAsync(IReadOnlyList<string> recipients, string message)
    {
        foreach (var batch in recipients.Chunk(25))
        {
            await Task.WhenAll(batch.Select(recipient => _sender.SendAsync(recipient, message)));
        }
    }
}
