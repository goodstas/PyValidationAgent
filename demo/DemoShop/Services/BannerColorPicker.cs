namespace DemoShop.Services;

public sealed class BannerColorPicker
{
    private static readonly string[] Palette = ["#2563eb", "#16a34a", "#f59e0b", "#db2777"];

    public string NextColor()
    {
        int index = Random.Shared.Next(Palette.Length);
        return Palette[index];
    }
}
