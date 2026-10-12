using DemoShop.Data;
using Microsoft.AspNetCore.Mvc;

namespace DemoShop.Controllers;

[ApiController]
[Route("customers")]
public sealed class CustomerSearchController : ControllerBase
{
    private readonly IDbConnectionFactory _connections;

    public CustomerSearchController(IDbConnectionFactory connections)
    {
        _connections = connections;
    }

    [HttpGet("search")]
    public IActionResult Search()
    {
        string name = Request.Query["name"].ToString();
        using var connection = _connections.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT Id, Name FROM Customers WHERE Name LIKE '%" + name + "%'";
        return Ok(command.ExecuteScalar());
    }

    [HttpGet("by-email")]
    public IActionResult ByEmail()
    {
        string email = Request.Query["email"].ToString();
        using var connection = _connections.Open();
        using var command = connection.CreateCommand();
        command.CommandText = "SELECT Id, Name FROM Customers WHERE Email = @email";
        var parameter = command.CreateParameter();
        parameter.ParameterName = "@email";
        parameter.Value = email;
        command.Parameters.Add(parameter);
        return Ok(command.ExecuteScalar());
    }
}
