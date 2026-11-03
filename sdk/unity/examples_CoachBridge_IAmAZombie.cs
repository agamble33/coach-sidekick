// Coach in I'm A Zombie. Self-bootstrapping: nothing to add to a scene. At runtime it creates one
// "Coach" object (CoachClient + CoachArrow + this bridge), finds the player, camera and landmarks
// every zone, reports hunger/health events, and draws Coach's arrow, speech and meme card in-game.
//
// Setup: press F9 in Play mode, paste Base Url / Live Id / Consent Id from the Coach page (Live
// card > Game SDK > Copy for Unity), click Save. Values persist in PlayerPrefs.
// Turn on "Guide me" on the Coach page to get arrows. Part of the Coach hackathon submission;
// the game itself is the host, not the submission.
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using IAmAZombie.Core;
using IAmAZombie.Demo;
using IAmAZombie.Player;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

public class CoachBridge : MonoBehaviour
{
    const string PP = "coach.";
    CoachClient client; CoachArrow arrow;
    Transform player; HungerSystem hunger; DemoPlayerDriver driver;
    float lastHealth = 1f, idleSince, scanAt; Vector3 lastPos;
    bool showConfig, hooked;
    string cfgBase, cfgLive, cfgConsent;
    // in-game presentation
    string speech = ""; float speechUntil;
    Texture2D cardTex; string cardLine = ""; float cardUntil; AudioSource sfx;
    GUIStyle box, big, small;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Boot()
    {
        if (FindFirstObjectByType<CoachBridge>() != null) return;
        var go = new GameObject("Coach");
        DontDestroyOnLoad(go);
        go.AddComponent<CoachBridge>();
    }

    void Awake()
    {
        client = gameObject.AddComponent<CoachClient>();
        client.gameName = "I'm A Zombie: Sanctuary";
        client.postInterval = 1.0f;
        cfgBase = PlayerPrefs.GetString(PP + "base", "http://127.0.0.1:8000");
        cfgLive = PlayerPrefs.GetString(PP + "live", "");
        cfgConsent = PlayerPrefs.GetString(PP + "consent", "");
        Apply();
        arrow = BuildArrow();
        client.OnPoint.AddListener(arrow.Show);
        client.OnRoute.AddListener(arrow.ShowRoute);
        client.OnCallout.AddListener(t => { speech = t; speechUntil = Time.time + 8f; });
        client.OnReaction.AddListener((trigger, line, url) => StartCoroutine(ShowCard(line, url, trigger)));
        sfx = gameObject.AddComponent<AudioSource>(); sfx.playOnAwake = false; sfx.spatialBlend = 0f;
    }

    void Apply() { client.baseUrl = cfgBase.TrimEnd('/'); client.liveId = cfgLive.Trim(); client.consentId = cfgConsent.Trim(); }

    // ---- find the world each zone (the bootstrap rebuilds everything on a zone change) ----
    void Update()
    {
#if ENABLE_INPUT_SYSTEM
        if (Keyboard.current != null && Keyboard.current.f9Key.wasPressedThisFrame) showConfig = !showConfig;
#else
        if (Input.GetKeyDown(KeyCode.F9)) showConfig = !showConfig;
#endif
        if (Time.time < scanAt) return;
        scanAt = Time.time + 1.0f;
        var p = GameObject.FindWithTag("Player");
        if (p == null) { player = null; hooked = false; return; }
        if (player != p.transform)
        {
            player = p.transform; hooked = false;
            hunger = p.GetComponent<HungerSystem>(); driver = p.GetComponent<DemoPlayerDriver>();
            client.player = player; client.playerCamera = Camera.main;
            arrow.follow = player; lastPos = player.position; idleSince = Time.time;
            if (driver != null) lastHealth = driver.HealthNormalized;
        }
        if (!hooked && hunger != null)
        {
            hooked = true;
            hunger.OnCravingStart += () => client.ReportEvent("low_hp", "hunger maxed, craving");
            hunger.OnFeralStart += () => client.ReportEvent("dumb_play", "ate a human, feral burst");
            hunger.OnTurned += () => client.ReportEvent("died", "turned");
        }
        if (driver != null)
        {
            float h = driver.HealthNormalized;
            if (h < lastHealth - 0.25f) client.ReportEvent("took_damage", "lost " + Mathf.RoundToInt((lastHealth - h) * 100) + "% health");
            if (h < 0.2f && lastHealth >= 0.2f) client.ReportEvent("near_death", "health under 20%");
            lastHealth = h;
            if (driver.Stumbling) client.ReportEvent("missed_jump", "tripped while sprinting");
        }
        if ((player.position - lastPos).sqrMagnitude > 0.05f) { lastPos = player.position; idleSince = Time.time; }
        else if (Time.time - idleSince > 20f) { client.ReportEvent("idle", "no movement for 20 s"); idleSince = Time.time; }
        var gs = DemoGameState.Instance;
        if (gs != null && gs.State == DemoGameState.Outcome.Won && !wonReported) { wonReported = true; client.ReportEvent("objective_done", "reached the Sanctuary"); }

        // state for Coach
        client.playerHp = driver != null ? Mathf.RoundToInt(driver.HealthNormalized * 100) : 100;
        client.playerState = hunger == null ? "exploring" : hunger.IsFeral ? "feral" : hunger.IsCraving ? "craving" :
            (driver != null && driver.Disguised) ? "disguised" : (driver != null && driver.NearZombies) ? "in the horde" : "exploring";
        var lm = DemoLevelManager.Instance;
        client.objective = (lm != null ? lm.ZoneLabel + ". " : "") + "Reach the Sanctuary pad without turning. Eat animals, not humans"
            + (hunger != null ? ". Hunger " + Mathf.RoundToInt(hunger.Hunger) + "/100" : "");
        RebuildLandmarks();
    }
    bool wonReported;

    void RebuildLandmarks()
    {
        client.landmarks.Clear();
        var pad = FindFirstObjectByType<DemoObjective>();
        if (pad != null) client.landmarks.Add(new CoachLandmark { id = "sanctuary", label = "Sanctuary (the cure)", target = pad.transform });
        AddNearest<Feedable>("food", "Safe food", 2, f => f.Type == Feedable.FoodType.Animal);
        AddNearest<DemoDisguisePickup>("disguise", "Disguise", 1, null);
        AddNearest<DemoHumanHunter>("hunter", "Hunter (danger)", 2, null);
    }

    void AddNearest<T>(string id, string label, int count, System.Func<T, bool> ok) where T : MonoBehaviour
    {
        if (player == null) return;
        var all = FindObjectsByType<T>(FindObjectsSortMode.None);
        var list = new List<T>();
        foreach (var a in all) if (a != null && (ok == null || ok(a))) list.Add(a);
        list.Sort((a, b) => (a.transform.position - player.position).sqrMagnitude.CompareTo((b.transform.position - player.position).sqrMagnitude));
        for (int i = 0; i < Mathf.Min(count, list.Count); i++)
            client.landmarks.Add(new CoachLandmark { id = count == 1 ? id : id + "_" + (i + 1), label = label, target = list[i].transform });
    }

    // ---- presentation ----
    CoachArrow BuildArrow()
    {
        var root = new GameObject("CoachArrow");
        root.transform.SetParent(transform, false);
        var shaft = GameObject.CreatePrimitive(PrimitiveType.Cylinder); Destroy(shaft.GetComponent<Collider>());
        shaft.transform.SetParent(root.transform, false); shaft.transform.localRotation = Quaternion.Euler(90, 0, 0);
        shaft.transform.localScale = new Vector3(0.12f, 0.35f, 0.12f); shaft.transform.localPosition = new Vector3(0, 0, 0.1f);
        var head = GameObject.CreatePrimitive(PrimitiveType.Cube); Destroy(head.GetComponent<Collider>());
        head.transform.SetParent(root.transform, false); head.transform.localRotation = Quaternion.Euler(0, 45, 0);
        head.transform.localScale = new Vector3(0.3f, 0.12f, 0.3f); head.transform.localPosition = new Vector3(0, 0, 0.55f);
        var mat = new Material(Shader.Find("Universal Render Pipeline/Unlit") ?? Shader.Find("Unlit/Color"));
        mat.color = new Color(0.1f, 0.9f, 0.55f);
        shaft.GetComponent<Renderer>().material = mat; head.GetComponent<Renderer>().material = mat;
        var a = root.AddComponent<CoachArrow>(); a.offset = new Vector3(0, 2.2f, 0.8f); a.seconds = 12f;
        return a;
    }

    IEnumerator ShowCard(string line, string url, string trigger)
    {
        cardLine = line; cardUntil = Time.time + 3f;
        using (var req = UnityWebRequestTexture.GetTexture(url))
        {
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success) cardTex = DownloadHandlerTexture.GetContent(req);
        }
        // the sting lives next to the image on the server: swap the path the engine gave us
        string sound = url.Replace("/images/classic/", "/sounds/").Replace("/images/", "/sounds/");
        sound = sound.Substring(0, sound.LastIndexOf('/') + 1) + StingFor(trigger);
        using (var req = UnityWebRequestMultimedia.GetAudioClip(sound, AudioType.MPEG))
        {
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success) { sfx.clip = DownloadHandlerAudioClip.GetContent(req); sfx.Play(); }
        }
    }
    static string StingFor(string trigger)
    {
        switch (trigger)
        {
            case "missed_jump": return "womp.mp3"; case "dumb_play": return "bruh.mp3"; case "ignored_callout": return "scratch.mp3";
            case "rizz_detected": return "airhorn.mp3"; case "slow_reaction": return "boing.mp3"; case "near_death": return "gasp.mp3";
            case "whiff": return "scratch.mp3"; case "clutch": return "dingding.mp3"; default: return "cackle.mp3";
        }
    }

    void OnGUI()
    {
        if (box == null)
        {
            box = new GUIStyle(GUI.skin.box) { fontSize = 16, alignment = TextAnchor.MiddleLeft, wordWrap = true, padding = new RectOffset(12, 12, 8, 8) };
            box.normal.textColor = Color.white;
            big = new GUIStyle(GUI.skin.label) { fontSize = 18, fontStyle = FontStyle.Bold, wordWrap = true }; big.normal.textColor = Color.white;
            small = new GUIStyle(GUI.skin.label) { fontSize = 11 }; small.normal.textColor = new Color(0.5f, 0.75f, 1f);
        }
        float W = Screen.width, H = Screen.height;
        // status pill
        GUI.color = new Color(0, 0, 0, 0.6f); GUI.Box(new Rect(W - 150, 8, 142, 24), GUIContent.none); GUI.color = Color.white;
        GUI.Label(new Rect(W - 144, 10, 140, 20), client.Connected ? "COACH connected" : (string.IsNullOrEmpty(client.liveId) ? "COACH: press F9" : "COACH: no link"), small);
        // arrow label (2D, projected over the arrow)
        if (arrow != null && arrow.Active && Camera.main != null)
        {
            var sp = Camera.main.WorldToScreenPoint(arrow.transform.position + Vector3.up * 0.4f);
            if (sp.z > 0)
            {
                var r = new Rect(sp.x - 80, H - sp.y - 34, 160, 24);
                GUI.color = new Color(0.1f, 0.9f, 0.55f, 0.95f); GUI.Box(r, GUIContent.none); GUI.color = Color.white;
                var st = new GUIStyle(big) { alignment = TextAnchor.MiddleCenter, fontSize = 14 }; st.normal.textColor = new Color(0.02f, 0.2f, 0.1f);
                GUI.Label(r, arrow.LabelText, st);
            }
        }
        // speech
        if (Time.time < speechUntil && !string.IsNullOrEmpty(speech))
        {
            var r = new Rect(W * 0.2f, 24, W * 0.6f, 52);
            GUI.color = new Color(0.03f, 0.05f, 0.1f, 0.9f); GUI.Box(r, GUIContent.none); GUI.color = Color.white;
            GUI.Label(new Rect(r.x + 14, r.y + 6, r.width - 28, 20), "COACH", small);
            GUI.Label(new Rect(r.x + 14, r.y + 22, r.width - 28, 30), speech, big);
        }
        // meme card
        if (Time.time < cardUntil)
        {
            var r = new Rect(W - 372, H - 132, 360, 120);
            GUI.color = new Color(0.03f, 0.05f, 0.1f, 0.92f); GUI.Box(r, GUIContent.none); GUI.color = Color.white;
            if (cardTex != null) GUI.DrawTexture(new Rect(r.x + 10, r.y + 10, 100, 100), cardTex, ScaleMode.ScaleToFit);
            GUI.Label(new Rect(r.x + 120, r.y + 14, 230, 20), "COACH", small);
            GUI.Label(new Rect(r.x + 120, r.y + 36, 230, 70), cardLine, big);
        }
        if (!showConfig) return;
        var c = new Rect(W * 0.5f - 230, H * 0.5f - 110, 460, 220);
        GUI.color = new Color(0.03f, 0.05f, 0.1f, 0.95f); GUI.Box(c, GUIContent.none); GUI.color = Color.white;
        GUI.Label(new Rect(c.x + 16, c.y + 10, 420, 24), "Coach link (from the Coach page: Live card > Game SDK)", big);
        GUI.Label(new Rect(c.x + 16, c.y + 44, 100, 22), "Base URL"); cfgBase = GUI.TextField(new Rect(c.x + 120, c.y + 44, 320, 22), cfgBase);
        GUI.Label(new Rect(c.x + 16, c.y + 74, 100, 22), "Live id"); cfgLive = GUI.TextField(new Rect(c.x + 120, c.y + 74, 320, 22), cfgLive);
        GUI.Label(new Rect(c.x + 16, c.y + 104, 100, 22), "Consent id"); cfgConsent = GUI.TextField(new Rect(c.x + 120, c.y + 104, 320, 22), cfgConsent);
        if (GUI.Button(new Rect(c.x + 120, c.y + 140, 100, 28), "Save"))
        {
            PlayerPrefs.SetString(PP + "base", cfgBase); PlayerPrefs.SetString(PP + "live", cfgLive); PlayerPrefs.SetString(PP + "consent", cfgConsent); PlayerPrefs.Save();
            Apply(); showConfig = false;
        }
        if (GUI.Button(new Rect(c.x + 230, c.y + 140, 100, 28), "Close")) showConfig = false;
        GUI.Label(new Rect(c.x + 16, c.y + 178, 430, 36), string.IsNullOrEmpty(client.LastError) ? "F9 toggles this panel." : client.LastError, small);
    }
}
