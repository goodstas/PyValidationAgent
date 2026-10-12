using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Operations;

namespace SecureYourCode.PerformanceAnalyzer;

internal static class OperationHelpers
{
    public static IOperation Unwrap(IOperation operation)
    {
        while (true)
        {
            switch (operation)
            {
                case IConversionOperation conversion:
                    operation = conversion.Operand;
                    continue;
                case IParenthesizedOperation parenthesized:
                    operation = parenthesized.Operand;
                    continue;
                case IAwaitOperation awaitOperation:
                    operation = awaitOperation.Operation;
                    continue;
                default:
                    return operation;
            }
        }
    }

    /// <summary>The receiver of an instance call, or the `this` argument of an extension call.</summary>
    public static IOperation? Receiver(IInvocationOperation invocation)
    {
        if (invocation.Instance is not null)
        {
            return Unwrap(invocation.Instance);
        }

        if (invocation.TargetMethod.IsExtensionMethod && invocation.Arguments.Length > 0)
        {
            return Unwrap(invocation.Arguments[0].Value);
        }

        return null;
    }

    public static bool IsType(ITypeSymbol? type, string containingNamespace, string metadataName)
    {
        if (type is null)
        {
            return false;
        }

        var original = type.OriginalDefinition;
        return original.MetadataName == metadataName && original.ContainingNamespace?.ToDisplayString() == containingNamespace;
    }

    public static bool IsOrDerivesFrom(ITypeSymbol? type, string containingNamespace, string metadataName)
    {
        for (var current = type; current is not null; current = current.BaseType)
        {
            if (IsType(current, containingNamespace, metadataName))
            {
                return true;
            }
        }

        return false;
    }

    public static bool ImplementsGenericInterface(ITypeSymbol? type, string containingNamespace, string metadataName)
    {
        if (type is null)
        {
            return false;
        }

        if (IsType(type, containingNamespace, metadataName))
        {
            return true;
        }

        foreach (var iface in type.AllInterfaces)
        {
            if (IsType(iface, containingNamespace, metadataName))
            {
                return true;
            }
        }

        return false;
    }

    public static bool IsTaskType(ITypeSymbol? type) =>
        IsType(type, "System.Threading.Tasks", "Task") || IsType(type, "System.Threading.Tasks", "Task`1");
}
