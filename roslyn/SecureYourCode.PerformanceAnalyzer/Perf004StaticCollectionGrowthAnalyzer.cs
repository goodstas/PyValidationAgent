using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Diagnostics;
using Microsoft.CodeAnalysis.Operations;

namespace SecureYourCode.PerformanceAnalyzer;

/// <summary>
/// PERF004: a static Dictionary/ConcurrentDictionary/List field grown inside its containing type with no
/// Remove/TryRemove/RemoveAt/RemoveAll/RemoveRange/Clear of the same field anywhere in that type.
/// Conservative heuristic: no reachability proof. Static properties and DI singletons are out of scope.
/// </summary>
[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class Perf004StaticCollectionGrowthAnalyzer : DiagnosticAnalyzer
{
    private enum CollectionKind { None, Dictionary, ConcurrentDictionary, List }

    private static readonly ImmutableHashSet<string> DictionaryGrowth = ImmutableHashSet.Create("Add", "TryAdd");
    private static readonly ImmutableHashSet<string> ConcurrentGrowth = ImmutableHashSet.Create("TryAdd", "GetOrAdd", "AddOrUpdate");
    private static readonly ImmutableHashSet<string> ListGrowth = ImmutableHashSet.Create("Add", "AddRange", "Insert", "InsertRange");
    private static readonly ImmutableHashSet<string> Removal = ImmutableHashSet.Create("Remove", "TryRemove", "RemoveAt", "RemoveAll", "RemoveRange", "Clear");

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => ImmutableArray.Create(Descriptors.Perf004);

    public override void Initialize(AnalysisContext context)
    {
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.EnableConcurrentExecution();
        context.RegisterSymbolStartAction(OnTypeStart, SymbolKind.NamedType);
    }

    private sealed class TypeState
    {
        public readonly ConcurrentDictionary<IFieldSymbol, ConcurrentDictionary<Location, byte>> Growth = new(SymbolEqualityComparer.Default);
        public readonly ConcurrentDictionary<IFieldSymbol, byte> Removed = new(SymbolEqualityComparer.Default);
    }

    private static void OnTypeStart(SymbolStartAnalysisContext context)
    {
        var type = (INamedTypeSymbol)context.Symbol;
        var state = new TypeState();

        context.RegisterOperationAction(ctx => OnInvocation(ctx, type, state), OperationKind.Invocation);
        context.RegisterOperationAction(ctx => OnAssignment(ctx, type, state), OperationKind.SimpleAssignment);
        context.RegisterSymbolEndAction(ctx =>
        {
            foreach (var entry in state.Growth)
            {
                if (state.Removed.ContainsKey(entry.Key))
                {
                    continue;
                }

                foreach (var location in entry.Value.Keys)
                {
                    ctx.ReportDiagnostic(Diagnostic.Create(Descriptors.Perf004, location, entry.Key.Name, type.Name));
                }
            }
        });
    }

    private static IFieldSymbol? StaticCollectionField(IOperation? instance, INamedTypeSymbol containingType, out CollectionKind kind)
    {
        kind = CollectionKind.None;
        if (instance is null || OperationHelpers.Unwrap(instance) is not IFieldReferenceOperation fieldReference)
        {
            return null;
        }

        var field = fieldReference.Field;
        if (!field.IsStatic || !SymbolEqualityComparer.Default.Equals(field.ContainingType, containingType))
        {
            return null;
        }

        kind = Classify(field.Type);
        return kind == CollectionKind.None ? null : field;
    }

    private static CollectionKind Classify(ITypeSymbol type)
    {
        if (OperationHelpers.IsType(type, "System.Collections.Generic", "Dictionary`2"))
        {
            return CollectionKind.Dictionary;
        }

        if (OperationHelpers.IsType(type, "System.Collections.Concurrent", "ConcurrentDictionary`2"))
        {
            return CollectionKind.ConcurrentDictionary;
        }

        if (OperationHelpers.IsType(type, "System.Collections.Generic", "List`1"))
        {
            return CollectionKind.List;
        }

        return CollectionKind.None;
    }

    private static void OnInvocation(OperationAnalysisContext context, INamedTypeSymbol type, TypeState state)
    {
        var invocation = (IInvocationOperation)context.Operation;
        var field = StaticCollectionField(invocation.Instance, type, out var kind);
        if (field is null)
        {
            return;
        }

        var method = invocation.TargetMethod;

        // Resolved member check: the method must belong to the field's own collection type.
        if (!SymbolEqualityComparer.Default.Equals(method.ContainingType.OriginalDefinition, field.Type.OriginalDefinition))
        {
            return;
        }

        if (Removal.Contains(method.Name))
        {
            state.Removed.TryAdd(field, 0);
            return;
        }

        var growth = kind switch
        {
            CollectionKind.Dictionary => DictionaryGrowth,
            CollectionKind.ConcurrentDictionary => ConcurrentGrowth,
            CollectionKind.List => ListGrowth,
            _ => ImmutableHashSet<string>.Empty,
        };

        if (growth.Contains(method.Name))
        {
            state.Growth.GetOrAdd(field, _ => new ConcurrentDictionary<Location, byte>()).TryAdd(invocation.Syntax.GetLocation(), 0);
        }
    }

    private static void OnAssignment(OperationAnalysisContext context, INamedTypeSymbol type, TypeState state)
    {
        var assignment = (ISimpleAssignmentOperation)context.Operation;
        if (assignment.Target is not IPropertyReferenceOperation { Property.IsIndexer: true } indexer)
        {
            return;
        }

        var field = StaticCollectionField(indexer.Instance, type, out var kind);

        // List<T> indexer assignment replaces an existing slot: not growth.
        if (field is null || kind == CollectionKind.List)
        {
            return;
        }

        state.Growth.GetOrAdd(field, _ => new ConcurrentDictionary<Location, byte>()).TryAdd(assignment.Syntax.GetLocation(), 0);
    }
}
