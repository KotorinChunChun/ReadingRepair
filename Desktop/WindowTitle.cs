namespace ReadingRepair.Desktop;
internal static class WindowTitle
{
    public static string Create(string? page=null)
    {
        var v=typeof(WindowTitle).Assembly.GetName().Version!;
        var title=$"ReadingRepair - ver {v.Major}.{v.Minor}.{v.Build}";
        return string.IsNullOrWhiteSpace(page) ? title : $"{page} - {title}";
    }
}
