// Oyun Çeviri · Samsung TV helper. Installs and starts the Oyun Çeviri TV app on a Samsung (Tizen) TV whose
// Developer Mode is on with this PC's address as "Host PC IP" (the same way GameTranslator / Tizen Studio do it):
//   1. connect to the TV with sdb (port 26101), read its DUID and Tizen version,
//   2. if there is no valid certificate for this TV yet: sign in once with a Samsung account (the browser opens,
//      Samsung sends the result back to http://localhost:4794), get an author + a distributor certificate for this
//      TV from Samsung (svdca.samsungqbe.com),
//   3. sign the .wgt with them, install it, start the app.
// Commands (one JSON object per output line, the PC app reads them):
//   devmode <tv-ip>                                  {"devmode": true|false}
//   install <tv-ip> <file.wgt> <profiles-dir> <app-id> <package-id>
//   launch  <tv-ip> <app-id>
using System.Diagnostics;
using System.Formats.Asn1;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using TizenSdb;
using TizenSdb.SdbClient;
using TizenSdb.SigningManager;

internal static class Program
{
    private const int SdbPort = 26101;
    private static readonly TextWriter Out = Console.Out;

    private static void Emit(object value) { Out.WriteLine(JsonSerializer.Serialize(value)); Out.Flush(); }

    private static async Task<int> Main(string[] args)
    {
        try
        {
            switch (args.FirstOrDefault())
            {
                case "devmode" when args.Length >= 2:
                    Emit(new { devmode = await DevModeOn(args[1]) });
                    return 0;
                case "install" when args.Length >= 6:
                    await Install(args[1], args[2], args[3], args[4], args[5]);
                    Emit(new { ok = true });
                    return 0;
                case "selftest-sign" when args.Length >= 3:
                    // Signs a copy of the package with throw-away certificates: shows that signing works on it.
                    await SelfTestSign(args[1], args[2]);
                    Emit(new { ok = true });
                    return 0;
                case "launch" when args.Length >= 3:
                    await using (var device = await Connect(args[1]))
                        await device.ShellCommandAsync($"0 execute {args[2]}", CancellationToken.None);
                    Emit(new { ok = true });
                    return 0;
                default:
                    Emit(new { error = "usage: devmode <ip> | install <ip> <wgt> <profiles> <app-id> <pkg-id> | launch <ip> <app-id>", kind = "Usage" });
                    return 2;
            }
        }
        catch (HelperException e)
        {
            Emit(new { error = e.Message, kind = e.Kind });
            return 1;
        }
        catch (Exception e)
        {
            Emit(new { error = e.Message, kind = "Failed" });
            return 1;
        }
    }

    // ---------------------------------------------------------------- sdb

    /// <summary>Samsung accepts sdb only from the PC whose address was typed into the TV's Developer Mode window.</summary>
    private static async Task<bool> DevModeOn(string host)
    {
        using var tcp = new TcpClient();
        using var limit = new CancellationTokenSource(TimeSpan.FromSeconds(2));
        try { await tcp.ConnectAsync(host, SdbPort, limit.Token); return true; }
        catch (Exception e) when (e is SocketException or OperationCanceledException) { return false; }
    }

    private static async Task<SdbTcpDevice> Connect(string host)
    {
        if (!IPAddress.TryParse(host, out var address)) throw new HelperException("Unreachable", host);
        var device = new SdbTcpDevice(address, SdbPort);
        try
        {
            await device.ConnectAsync(CancellationToken.None);
            return device;
        }
        catch (Exception e)
        {
            await device.DisposeAsync();
            throw new HelperException("Unreachable", e.Message);
        }
    }

    private static async Task<string> ReadDuid(SdbTcpDevice device)
    {
        for (var attempt = 0; attempt < 3; attempt++)        // slow TVs answer empty the first time
        {
            var duid = (await device.ShellCommandAsync("0 getduid", CancellationToken.None)).Split('\n')[0].Trim();
            if (Regex.IsMatch(duid, @"^[A-Za-z0-9_\-+=/]{8,}$")) return duid;
            await Task.Delay(500);
        }
        throw new HelperException("Unreachable", "TV kimliği (DUID) okunamadı");
    }

    private static async Task Install(string host, string wgt, string profiles, string appId, string packageId)
    {
        Emit(new { step = "connecting" });
        await using var device = await Connect(host);
        var caps = await device.CapabilityAsync(CancellationToken.None);
        var platform = caps.GetValueOrDefault("platform_version", "").Trim();
        if (platform.Length > 0 && Version.TryParse(platform, out var v) && v < new Version(5, 0))
            throw new HelperException("TooOld", platform);
        var toolPath = caps.GetValueOrDefault("sdk_toolpath")?.Trim() is { Length: > 0 } p ? p : "/opt/usr/apps/tmp";

        var duid = await ReadDuid(device);
        var dir = Path.Combine(profiles, Regex.Replace(duid, @"[^A-Za-z0-9_\-]", "_"));
        var profile = Profile.In(dir);
        if (!profile.IsValid())
        {
            var account = await SamsungLogin.SignIn();
            Emit(new { step = "certificate" });
            profile = await Certificates.Create(duid, account, dir);
        }

        Emit(new { step = "signing" });
        var staged = Path.Combine(Path.GetTempPath(), $"oyunceviri-{Guid.NewGuid():N}.wgt");
        File.Copy(wgt, staged);
        try
        {
            await TizenWgtSigner.ReSignWgtWithCertsInPlace(staged, profile.Author, profile.Distributor, profile.Password);
            Emit(new { step = "installing" });
            var log = await Capture(() => new TizenInstaller(staged, device, toolPath).InstallApp());
            if (Failed(log))
            {
                // An older copy signed with another certificate ("author certificate not match"): remove, try again.
                Emit(new { step = "reinstalling" });
                foreach (var id in new[] { appId, packageId })
                {
                    try { await device.ShellCommandAsync($"0 vd_appuninstall {id}", CancellationToken.None); }
                    catch (Exception) { /* try the other id */ }
                }
                log = await Capture(() => new TizenInstaller(staged, device, toolPath).InstallApp());
                if (Failed(log)) throw new HelperException("InstallFailed", Tail(log));
            }
        }
        finally
        {
            try { File.Delete(staged); } catch (Exception) { /* the installer may still hold it; temp folder */ }
        }
        Emit(new { step = "starting" });
        try { await device.ShellCommandAsync($"0 execute {appId}", CancellationToken.None); } catch (Exception) { }
    }

    private static async Task SelfTestSign(string wgt, string output)
    {
        var dir = Path.Combine(Path.GetTempPath(), $"oyunceviri-selftest-{Guid.NewGuid():N}");
        Directory.CreateDirectory(dir);
        const string password = "selftest";
        foreach (var name in new[] { "author", "distributor" })
        {
            using var key = RSA.Create(2048);
            var request = new CertificateRequest($"CN=OyunCeviri {name} test", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
            using var cert = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(30));
            await File.WriteAllBytesAsync(Path.Combine(dir, $"{name}.p12"), cert.Export(X509ContentType.Pkcs12, password));
        }
        File.Copy(wgt, output, overwrite: true);
        await TizenWgtSigner.ReSignWgtWithCertsInPlace(output, Path.Combine(dir, "author.p12"), Path.Combine(dir, "distributor.p12"), password);
        Directory.Delete(dir, recursive: true);
    }

    /// <summary>The installer writes its result to the console; the TV reports success even when it failed.</summary>
    private static async Task<string> Capture(Func<Task> body)
    {
        var writer = new StringWriter();
        Console.SetOut(writer);
        try { await body(); }
        catch (Exception e) { writer.WriteLine($"install failed: {e.Message}"); }
        finally { Console.SetOut(Out); }
        return writer.ToString();
    }

    private static bool Failed(string log) =>
        log.Contains("install failed", StringComparison.OrdinalIgnoreCase) ||
        log.Contains("val[fail]", StringComparison.OrdinalIgnoreCase) ||
        log.Contains("not enough space", StringComparison.OrdinalIgnoreCase);

    private static string Tail(string log) => log.Length <= 400 ? log.Trim() : log[^400..].Trim();
}

internal sealed class HelperException(string kind, string message) : Exception(message)
{
    public string Kind { get; } = kind;
}

// ---------------------------------------------------------------- Samsung account

internal sealed record Account(string Token, string UserId, string Email);

internal static class SamsungLogin
{
    private const string Gate = "https://account.samsung.com/accounts/be1dce529476c1a6d407c4c7578c31bd/signInGate";
    private const string ClientId = "v285zxnl3h";                 // Samsung's Tizen certificate sign-in
    private const string State = "accountcheckdogeneratedstatetext";
    private const int Port = 4794;
    private const string CallbackPath = "/signin/callback";

    public static string Url => $"{Gate}?locale=&clientId={ClientId}" +
        $"&redirect_uri={Uri.EscapeDataString($"http://localhost:{Port}{CallbackPath}")}&state={State}&tokenType=TOKEN";

    public static async Task<Account> SignIn()
    {
        var listener = new TcpListener(IPAddress.IPv6Any, Port);
        listener.Server.DualMode = true;
        try { listener.Start(); }
        catch (SocketException e) { throw new HelperException("LoginFailed", $"port {Port}: {e.Message}"); }
        using var limit = new CancellationTokenSource(TimeSpan.FromMinutes(10));
        try
        {
            Console.Out.Flush();
            Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
            Out(new { step = "signin", url = Url });
            while (true)
            {
                using var client = await listener.AcceptTcpClientAsync(limit.Token);
                await using var stream = client.GetStream();
                var (method, path, body) = await Read(stream, limit.Token);
                var account = method == "POST" && path.StartsWith(CallbackPath) ? Parse(body) : null;
                var page = account is not null
                    ? "<h2>Samsung girişi tamam.</h2><p>Bu sekmeyi kapatabilirsin; Oyun Çeviri kuruluma devam ediyor.</p>"
                    : "<p>Bekleniyor…</p>";
                var bytes = Encoding.UTF8.GetBytes($"<!doctype html><meta charset=utf-8><body style='font-family:sans-serif'>{page}");
                var head = Encoding.ASCII.GetBytes($"HTTP/1.1 {(account is not null ? 200 : 404)} OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {bytes.Length}\r\nConnection: close\r\n\r\n");
                await stream.WriteAsync(head, limit.Token);
                await stream.WriteAsync(bytes, limit.Token);
                if (account is not null) return account;
            }
        }
        catch (OperationCanceledException)
        {
            throw new HelperException("LoginFailed", "Samsung girişi 10 dakikada tamamlanmadı");
        }
        finally
        {
            listener.Stop();
        }
    }

    private static void Out(object value)
    {
        var w = Console.Out;
        w.WriteLine(JsonSerializer.Serialize(value));
        w.Flush();
    }

    private static Account? Parse(string body)
    {
        string? state = null, code = null;
        foreach (var part in body.Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var pair = part.Split('=', 2);
            if (pair.Length != 2) continue;
            if (pair[0] == "state") state = WebUtility.UrlDecode(pair[1]);
            if (pair[0] == "code") code = Uri.UnescapeDataString(pair[1]);
        }
        if (state != State || string.IsNullOrWhiteSpace(code)) return null;
        try
        {
            using var json = JsonDocument.Parse(code);
            string? Text(string name) => json.RootElement.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;
            return Text("access_token") is { Length: > 0 } token && Text("userId") is { Length: > 0 } user
                ? new Account(token, user, Text("inputEmailID") ?? "")
                : null;
        }
        catch (JsonException) { return null; }
    }

    private static async Task<(string, string, string)> Read(NetworkStream stream, CancellationToken token)
    {
        var buffer = new byte[16384];
        var data = new MemoryStream();
        int end;
        while ((end = HeaderEnd(data)) < 0)
        {
            var n = await stream.ReadAsync(buffer, token);
            if (n <= 0 || data.Length > 1 << 20) return ("", "", "");
            data.Write(buffer, 0, n);
        }
        var bytes = data.ToArray();
        var lines = Encoding.ASCII.GetString(bytes, 0, end).Split("\r\n");
        var request = lines[0].Split(' ');
        var length = 0;
        foreach (var line in lines)
            if (line.StartsWith("Content-Length:", StringComparison.OrdinalIgnoreCase)) int.TryParse(line[15..].Trim(), out length);
        var body = new MemoryStream();
        body.Write(bytes, end + 4, bytes.Length - end - 4);
        while (body.Length < length)
        {
            var n = await stream.ReadAsync(buffer, token);
            if (n <= 0) break;
            body.Write(buffer, 0, n);
        }
        return (request.ElementAtOrDefault(0) ?? "", request.ElementAtOrDefault(1) ?? "", Encoding.UTF8.GetString(body.ToArray()));
    }

    private static int HeaderEnd(MemoryStream s)
    {
        var b = s.GetBuffer();
        for (var i = 0; i + 3 < s.Length; i++)
            if (b[i] == '\r' && b[i + 1] == '\n' && b[i + 2] == '\r' && b[i + 3] == '\n') return i;
        return -1;
    }
}

// ---------------------------------------------------------------- certificates for one TV

internal sealed record Profile(string Author, string Distributor, string Password)
{
    public static Profile In(string dir) => new(Path.Combine(dir, "author.p12"), Path.Combine(dir, "distributor.p12"),
        File.Exists(Path.Combine(dir, "password.txt")) ? File.ReadAllText(Path.Combine(dir, "password.txt")).Trim() : "");

    public bool IsValid()
    {
        if (!File.Exists(Author) || !File.Exists(Distributor) || Password.Length == 0) return false;
        try
        {
            foreach (var path in new[] { Author, Distributor })
            {
                using var cert = X509CertificateLoader.LoadPkcs12FromFile(path, Password, X509KeyStorageFlags.EphemeralKeySet);
                if (cert.NotBefore > DateTime.UtcNow || cert.NotAfter < DateTime.UtcNow.AddDays(1)) return false;
            }
            return true;
        }
        catch (CryptographicException) { return false; }
    }
}

internal static class Certificates
{
    private const string Authors = "https://svdca.samsungqbe.com/apis/v3/authors";
    private const string DistributorProfile = "https://svdca.samsungqbe.com/apis/v1/distributors";
    private const string Distributors = "https://svdca.samsungqbe.com/apis/v3/distributors";
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(60) };

    public static async Task<Profile> Create(string duid, Account account, string dir)
    {
        using var key = RSA.Create(2048);
        var authorCsr = Csr(new CertificateRequest("CN=OyunCeviri", key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1));
        var subject = new X500DistinguishedNameBuilder();
        subject.AddCommonName("TizenSDK");
        if (!string.IsNullOrWhiteSpace(account.Email)) subject.AddEmailAddress(account.Email);
        var distributor = new CertificateRequest(subject.Build(), key, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        var san = new AsnWriter(AsnEncodingRules.DER);
        using (san.PushSequence())
            foreach (var uri in new[] { "URN:tizen:packageid=", $"URN:tizen:deviceid={duid}" })
                san.WriteCharacterString(UniversalTagNumber.IA5String, uri, new Asn1Tag(TagClass.ContextSpecific, 6));
        distributor.CertificateExtensions.Add(new X509Extension("2.5.29.17", san.Encode(), critical: false));
        var distributorCsr = Csr(distributor);

        var author = await Post(Authors, account, authorCsr, "author.csr", false);
        var deviceProfile = await Post(DistributorProfile, account, distributorCsr, "distributor.csr", true);
        var dist = await Post(Distributors, account, distributorCsr, "distributor.csr", true);

        Directory.CreateDirectory(dir);
        var password = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
        var profile = new Profile(Path.Combine(dir, "author.p12"), Path.Combine(dir, "distributor.p12"), password);
        await File.WriteAllBytesAsync(profile.Author, Pkcs12(Load(author), key, password));
        await File.WriteAllBytesAsync(profile.Distributor, Pkcs12(Load(dist), key, password));
        await File.WriteAllBytesAsync(Path.Combine(dir, "device-profile.xml"), deviceProfile);
        await File.WriteAllTextAsync(Path.Combine(dir, "password.txt"), password);
        await File.WriteAllTextAsync(Path.Combine(dir, "duid.txt"), duid);
        return profile;
    }

    private static byte[] Csr(CertificateRequest request) => Encoding.ASCII.GetBytes(request.CreateSigningRequestPem());

    private static async Task<byte[]> Post(string url, Account account, byte[] csr, string name, bool distributor)
    {
        using var form = new MultipartFormDataContent
        {
            { new StringContent(account.Token), "access_token" },
            { new StringContent(account.UserId), "user_id" },
            { new StringContent("VD"), "platform" },
        };
        if (distributor)
        {
            form.Add(new StringContent("public"), "privilege_level");
            form.Add(new StringContent("Individual"), "developer_type");
        }
        form.Add(new ByteArrayContent(csr), "csr", name);
        using var response = await Http.PostAsync(url, form);
        var body = await response.Content.ReadAsByteArrayAsync();
        if (!response.IsSuccessStatusCode)
            throw new HelperException("CertificateFailed", $"{(int)response.StatusCode} {Encoding.UTF8.GetString(body.AsSpan(0, Math.Min(body.Length, 300)))}");
        return body;
    }

    private static X509Certificate2 Load(byte[] data)
    {
        var text = Encoding.ASCII.GetString(data);
        return text.Contains("-----BEGIN CERTIFICATE-----") ? X509Certificate2.CreateFromPem(text) : X509CertificateLoader.LoadCertificate(data);
    }

    private static byte[] Pkcs12(X509Certificate2 leaf, RSA key, string password)
    {
        using var withKey = leaf.CopyWithPrivateKey(key);
        var chain = new X509Certificate2Collection { withKey };
        var intermediate = SamsungCa().FirstOrDefault(ca => ca.Subject == leaf.Issuer && ca.Subject != ca.Issuer);
        if (intermediate is not null) chain.Add(intermediate);
        return chain.ExportPkcs12(new PbeParameters(PbeEncryptionAlgorithm.TripleDes3KeyPkcs12, HashAlgorithmName.SHA1, 2048), password);
    }

    private static IEnumerable<X509Certificate2> SamsungCa()
    {
        var assembly = typeof(Certificates).Assembly;
        foreach (var name in new[] { "vd_tizen_dev_author_ca", "author_ca", "vd_tizen_dev_public2", "public2" })
        {
            using var stream = assembly.GetManifestResourceStream($"ca.{name}.pem");
            if (stream is null) continue;
            using var reader = new StreamReader(stream);
            yield return X509Certificate2.CreateFromPem(reader.ReadToEnd());
        }
    }
}
