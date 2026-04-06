(function () {
  "use strict";

  // ============================================================
  // DOM 引用
  // ============================================================
  var wsUrlInput     = document.getElementById("wsUrlInput");
  var tokenInput     = document.getElementById("tokenInput");
  var connectBtn     = document.getElementById("connectBtn");
  var disconnectBtn  = document.getElementById("disconnectBtn");
  var sendTextBtn    = document.getElementById("sendTextBtn");
  var statusText     = document.getElementById("statusText");
  var statusDot      = document.getElementById("statusDot");
  var textInput      = document.getElementById("textInput");
  var audioFileInput = document.getElementById("audioFileInput");
  var sendAudioBtn   = document.getElementById("sendAudioBtn");
  var audioUploadText= document.getElementById("audioUploadText");
  var logBox         = document.getElementById("logBox");
  var qrText         = document.getElementById("qrText");
  var qrImage        = document.getElementById("qrImage");
  var audioPlayer    = document.getElementById("audioPlayer");
  var audioText      = document.getElementById("audioText");
  var effectText     = document.getElementById("effectText");
  var heartEffect    = document.getElementById("heartEffect");
  var live2dContainer= document.getElementById("live2dContainer");
  var modelText      = document.getElementById("modelText");
  var mouthBarInner  = document.getElementById("mouthBarInner");
  var chatHistory    = document.getElementById("chatHistory");
  var clearChatBtn   = document.getElementById("clearChatBtn");
  var settingsBtn    = document.getElementById("settingsBtn");
  var settingsPanel  = document.getElementById("settingsPanel");
  var settingsCloseBtn = document.getElementById("settingsCloseBtn");
  var voiceBtn       = document.getElementById("voiceBtn");
  var bottomBar      = document.getElementById("bottomBar");
  var inputModeToggle = document.getElementById("inputModeToggle");
  var voiceInputPanel = document.getElementById("voiceInputPanel");
  var textInputPanel  = document.getElementById("textInputPanel");
  // 天气 overlay
  var weatherOverlay = document.getElementById("weatherOverlay");
  var weatherCity    = document.getElementById("weatherCity");
  var weatherDays    = document.getElementById("weatherDays");

  // ============================================================
  // 状态变量
  // ============================================================
  var socket = null;
  var isConnected = false;
  var reconnectTimer = null;
  var pingTimer = null;
  var live2dLoaded = false;
  var audioCtx = null;
  var voicePlaybackSource = null;
  var ttsPlayGeneration = 0;
  var ttsBlobUrl = null;
  var audioUnlocked = false;
  var audioUnlocking = false;
  var mouthRaf = null;
  var mediaSource = null;
  var mediaSourceUrl = null;
  var sourceBuffer = null;
  var sourceQueue = [];
  var useMse = false;
  var fallbackChunks = [];
  var userRequestedDisconnect = false;
  var isRecording = false;
  var recognition = null;
  // 语音：iPad 上系统麦克风弹窗需要松手去点「允许」，不能再把「授权前松手」当成取消，否则永远录不上
  var voiceGumPending = false;           // 是否正在等待 getUserMedia 回调
  var voiceMediaRecorder = null;         // Safari 上 ScriptProcessor 不可用时改用 MediaRecorder
  var voiceRecorderChunks = [];          // MediaRecorder 分片
  var voiceCaptureKind = "";             // "" | "script" | "mr"

  // 模型 JSON 加版本参数，避免浏览器缓存旧版（含日语 sound 的配置）
  var MODEL_JSON_VER = "20260406m";
  var MODEL_URLS = {
    "default": "./assets/models/shizuku/shizuku.model.json?v=" + MODEL_JSON_VER,
    "sport":   "./assets/models/shizuku/shizuku.model.json?v=" + MODEL_JSON_VER,
    "cute":    "./assets/models/shizuku/shizuku.model.json?v=" + MODEL_JSON_VER,
    "tech":    "./assets/models/shizuku/shizuku.model.json?v=" + MODEL_JSON_VER
  };

  // ============================================================
  // 工具函数
  // ============================================================

  function nowTs() { return Math.floor(Date.now() / 1000); }

  function traceId(prefix) { return prefix + "-" + String(Date.now()); }

  function timeLabel() {
    var d = new Date();
    var h = d.getHours();
    var m = d.getMinutes();
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function appendLog(label, obj) {
    if (!logBox) { return; }
    var text = "[" + new Date().toLocaleTimeString() + "] " + label + "\n";
    if (typeof obj === "string") {
      text += obj;
    } else {
      try { text += JSON.stringify(obj, null, 2); } catch (e) { text += String(obj); }
    }
    text += "\n\n";
    logBox.textContent = text + logBox.textContent;
  }

  function setStatus(text, dotClass) {
    if (statusText) { statusText.textContent = text; }
    if (statusDot) {
      statusDot.className = "status-dot " + (dotClass || "disconnected");
    }
  }

  /**
   * 根据当前页面地址推导 WebSocket URL（走 nginx 的 /ws 反代）。
   * 从 https 页面连接 ws:// 会被浏览器按「混合内容」拦截，Safari/iPad 会一直停在「连接中」。
   */
  function defaultWsUrlFromPage() {
    var p = window.location.protocol;
    var h = window.location.host;
    if (p === "https:") {
      return "wss://" + h + "/ws";
    }
    if (p === "http:") {
      return "ws://" + h + "/ws";
    }
    return "ws://" + (window.location.hostname || "127.0.0.1") + ":8765";
  }

  function safeSend(type, payload, customTraceId) {
    if (!socket || socket.readyState !== 1) {
      appendLog("WARN", "当前未连接，消息未发送: " + type);
      return;
    }
    var message = {
      type: String(type || "").toUpperCase(),
      payload: payload || {},
      trace_id: customTraceId || traceId("client"),
      timestamp: nowTs()
    };
    socket.send(JSON.stringify(message));
    appendLog("SEND " + message.type, message);
  }

  // ============================================================
  // 聊天历史 —— 消息气泡
  // ============================================================

  /**
   * 从 ASR 结果中只取「识别文本」，忽略 confidence、JSON 整包等（聊天区不展示调试字段）
   */
  function normalizeUserAsrText(payload) {
    var raw = payload && payload.text;
    if (raw == null) { return ""; }
    if (typeof raw === "object") {
      if (typeof raw.text === "string") { return String(raw.text).trim(); }
      if (typeof raw.transcript === "string") { return String(raw.transcript).trim(); }
      return "";
    }
    var s = String(raw).trim();
    if (!s) { return ""; }
    var c0 = s.charAt(0);
    if (c0 === "{" && s.indexOf("}") > 0) {
      // 标准 JSON
      try {
        var o = JSON.parse(s);
        if (typeof o === "string") { return o.trim(); }
        if (o && typeof o.text === "string") { return String(o.text).trim(); }
        if (o && typeof o.transcript === "string") { return String(o.transcript).trim(); }
        if (o && typeof o.result === "string") { return String(o.result).trim(); }
      } catch (e) { /* 非标准 JSON，尝试 Python dict 格式 */ }
      // Python dict 格式：{'confidence': 0, 'text': '你好'}
      var m = s.match(/'text'\s*:\s*'([\s\S]*?)'\s*[,}]/);
      if (m && m[1]) { return m[1].trim(); }
    }
    if (c0 === "[" && s.indexOf("]") > 0) {
      try {
        var arr = JSON.parse(s);
        if (Array.isArray(arr) && arr[0] && typeof arr[0].text === "string") { return String(arr[0].text).trim(); }
      } catch (e) {}
    }
    return s;
  }

  /**
   * 添加一条消息气泡到聊天历史
   * @param {string} role  "user" | "ai" | "xiaozhi" | "system"
   * @param {string} text  消息内容
   */
  function addMessage(role, text) {
    if (!chatHistory || !text) { return; }

    var row = document.createElement("div");
    row.className = "msg-row" +
      (role === "user"   ? " msg-user" :
       role === "system" ? " msg-system" : " msg-ai");

    if (role === "ai" || role === "xiaozhi") {
      var av = document.createElement("div");
      av.className = "msg-avatar" + (role === "xiaozhi" ? " avatar-xiaozhi" : "");
      av.textContent = role === "xiaozhi" ? "小智" : "AI";
      row.appendChild(av);
    }

    var body = document.createElement("div");
    body.className = "msg-body";

    if (role !== "system") {
      var timeEl = document.createElement("div");
      timeEl.className = "msg-time";
      timeEl.textContent = timeLabel();
      body.appendChild(timeEl);
    }

    var bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.textContent = text;
    body.appendChild(bubble);

    row.appendChild(body);
    chatHistory.appendChild(row);

    // 始终滚动到最新消息
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }

  function clearChat() {
    if (!chatHistory) { return; }
    while (chatHistory.firstChild) {
      chatHistory.removeChild(chatHistory.firstChild);
    }
    addMessage("system", "聊天记录已清除");
  }

  if (clearChatBtn) { clearChatBtn.onclick = clearChat; }

  // ============================================================
  // 设置面板
  // ============================================================

  function openSettings() {
    if (settingsPanel) {
      settingsPanel.className = settingsPanel.className.replace(" hidden", "").replace("hidden", "");
    }
  }

  function closeSettings() {
    if (settingsPanel && settingsPanel.className.indexOf("hidden") === -1) {
      settingsPanel.className += " hidden";
    }
  }

  if (settingsBtn)      { settingsBtn.onclick      = openSettings; }
  if (settingsCloseBtn) { settingsCloseBtn.onclick = closeSettings; }

  // ============================================================
  // 底部输入：默认语音（微信式），可切换键盘文字
  // ============================================================

  var inputModeVoicePrimary = true;

  function syncAppBodyBottom() {
    var body = document.querySelector(".app-body");
    if (!bottomBar || !body) { return; }
    body.style.bottom = Math.ceil(bottomBar.getBoundingClientRect().height) + "px";
  }

  function applyInputMode(voicePrimary) {
    inputModeVoicePrimary = !!voicePrimary;
    try { localStorage.setItem("pad_input_voice_primary", inputModeVoicePrimary ? "1" : "0"); } catch (e) {}
    if (!voiceInputPanel || !textInputPanel || !bottomBar || !inputModeToggle) { return; }
    if (inputModeVoicePrimary) {
      voiceInputPanel.className = "input-panel voice-input-panel";
      textInputPanel.className = "input-panel text-input-panel hidden";
      bottomBar.className = "bottom-bar bottom-bar--voice";
      inputModeToggle.innerHTML = "&#9000;";
      inputModeToggle.setAttribute("title", "切换到文字输入");
    } else {
      voiceInputPanel.className = "input-panel voice-input-panel hidden";
      textInputPanel.className = "input-panel text-input-panel";
      bottomBar.className = "bottom-bar bottom-bar--text";
      inputModeToggle.innerHTML = "&#127908;";
      inputModeToggle.setAttribute("title", "切换到语音输入");
      if (textInput) {
        try { textInput.focus(); } catch (e) {}
      }
    }
    setTimeout(syncAppBodyBottom, 0);
  }

  try {
    var savedMode = localStorage.getItem("pad_input_voice_primary");
    if (savedMode === "0") { inputModeVoicePrimary = false; }
  } catch (e) {}

  if (inputModeToggle) {
    inputModeToggle.addEventListener("click", function () {
      applyInputMode(!inputModeVoicePrimary);
    });
  }

  // ============================================================
  // 语音输入（getUserMedia + WAV）
  // iPad：系统麦克风授权弹窗需要松手去点「允许」，旧逻辑在 touchend 里「取消」会把流扔掉，表现为完全没反应
  // 新逻辑：pending 阶段松手不取消；支持 PointerEvent；ScriptProcessor 失败时用 MediaRecorder + decodeAudioData
  // ============================================================

  var voiceMediaStream  = null;
  var voiceAudioCtx     = null;
  var voiceScriptNode   = null;
  var voiceMuteGain     = null;
  var voiceBuffers      = [];
  var voiceSampleRate   = 44100;

  function stopVoiceTracks(stream) {
    if (!stream) { return; }
    try {
      var tr = stream.getTracks();
      var i;
      for (i = 0; i < tr.length; i += 1) { tr[i].stop(); }
    } catch (e0) {}
  }

  /** ScriptProcessor 不可用时（新版 Safari），用 MediaRecorder 录成 mp4/webm 再解码成 PCM → WAV */
  function startMediaRecorderFromStream(stream) {
    voiceCaptureKind = "mr";
    try {
      if (voiceAudioCtx) { voiceAudioCtx.close(); }
    } catch (e1) {}
    voiceAudioCtx = null;
    voiceScriptNode = null;
    voiceMuteGain = null;
    voiceMediaStream = stream;

    if (typeof MediaRecorder === "undefined") {
      voiceGumPending = false;
      stopVoiceTracks(stream);
      addMessage("system", "浏览器不支持 MediaRecorder，无法录音");
      return;
    }

    var mime = "";
    var candidates = ["audio/mp4", "audio/mp4;codecs=mp4a.40.2", "audio/webm;codecs=opus", "audio/webm"];
    var ci;
    for (ci = 0; ci < candidates.length; ci += 1) {
      if (MediaRecorder.isTypeSupported(candidates[ci])) {
        mime = candidates[ci];
        break;
      }
    }

    try {
      voiceMediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    } catch (e2) {
      try {
        voiceMediaRecorder = new MediaRecorder(stream);
      } catch (e3) {
        voiceGumPending = false;
        stopVoiceTracks(stream);
        addMessage("system", "无法启动录音器: " + String(e3));
        return;
      }
    }

    voiceRecorderChunks = [];
    voiceMediaRecorder.ondataavailable = function (ev) {
      if (ev.data && ev.data.size > 0) { voiceRecorderChunks.push(ev.data); }
    };
    voiceMediaRecorder.onstop = function () {
      voiceCaptureKind = "";
      var blob = new Blob(voiceRecorderChunks, {
        type: (voiceMediaRecorder && voiceMediaRecorder.mimeType) || mime || "audio/mp4"
      });
      voiceRecorderChunks = [];
      voiceMediaRecorder = null;
      stopVoiceTracks(voiceMediaStream);
      voiceMediaStream = null;

      if (blob.size < 160) {
        addMessage("system", "录音过短，请重试");
        return;
      }

      var reader = new FileReader();
      reader.onload = function () {
        var ab = reader.result;
        if (!ab) {
          addMessage("system", "读取录音失败");
          return;
        }
        var Dec = window.AudioContext || window.webkitAudioContext;
        if (!Dec) {
          addMessage("system", "无法解码录音");
          return;
        }
        var decCtx = new Dec();
        var buf = ab.slice ? ab.slice(0) : ab;
        decCtx.decodeAudioData(
          buf,
          function (audioBuf) {
            try {
              var ch = audioBuf.numberOfChannels > 0 ? audioBuf.getChannelData(0) : new Float32Array(0);
              var sr = audioBuf.sampleRate;
              var pcm16 = new Int16Array(ch.length);
              var pi;
              for (pi = 0; pi < ch.length; pi += 1) {
                var s = Math.max(-1, Math.min(1, ch[pi]));
                pcm16[pi] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
              }
              var wavBytes = encodeWav(pcm16, sr);
              appendLog("INFO", "MediaRecorder → WAV " + wavBytes.length + " bytes");
              sendVoiceWav(wavBytes);
            } catch (e4) {
              addMessage("system", "处理录音失败: " + String(e4));
            } finally {
              try { decCtx.close(); } catch (e5) {}
            }
          },
          function () {
            try { decCtx.close(); } catch (e6) {}
            addMessage("system", "无法解码录音格式，请重试或使用文字输入");
            appendLog("WARN", "decodeAudioData 失败");
          }
        );
      };
      reader.onerror = function () {
        addMessage("system", "读取录音数据失败");
      };
      reader.readAsArrayBuffer(blob);
    };

    try {
      voiceMediaRecorder.start(120);
      isRecording = true;
      voiceGumPending = false;
      if (voiceBtn) { voiceBtn.className = "btn-voice-hold recording"; }
      addMessage("system", "正在录音：松手结束并发送（若已松手授权麦克风，请再点一下麦克风结束）");
      appendLog("INFO", "MediaRecorder 录音 mime=" + (mime || "default"));
    } catch (e7) {
      voiceGumPending = false;
      stopVoiceTracks(stream);
      addMessage("system", "录音启动失败: " + String(e7));
    }
  }

  function startVoiceRecord() {
    if (isRecording) { return; }
    if (voiceGumPending) { return; }
    if (voiceMediaRecorder && voiceMediaRecorder.state === "recording") { return; }

    voiceGumPending = true;
    voiceCaptureKind = "";
    voiceMediaRecorder = null;
    voiceRecorderChunks = [];

    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) {
      voiceGumPending = false;
      addMessage("system", "当前浏览器不支持 Web Audio");
      appendLog("WARN", "AudioContext 不可用");
      return;
    }
    try {
      if (voiceAudioCtx) {
        try { voiceAudioCtx.close(); } catch (e8) {}
        voiceAudioCtx = null;
      }
      voiceAudioCtx = new Ctx();
      voiceSampleRate = voiceAudioCtx.sampleRate;
      if (voiceAudioCtx.state === "suspended" && voiceAudioCtx.resume) {
        voiceAudioCtx.resume();
      }
    } catch (e9) {
      voiceGumPending = false;
      appendLog("WARN", "AudioContext 创建失败: " + String(e9));
      addMessage("system", "无法初始化录音环境，请刷新后重试");
      return;
    }

    addMessage("system", "正在请求麦克风…（弹出系统对话框时请点「允许」）");

    function onStream(stream) {
      voiceGumPending = false;
      voiceMediaStream = stream;
      if (!voiceAudioCtx) {
        appendLog("WARN", "AudioContext 丢失");
        return;
      }

      try {
        var source = voiceAudioCtx.createMediaStreamSource(stream);
        voiceScriptNode = voiceAudioCtx.createScriptProcessor(4096, 1, 1);
        voiceMuteGain = voiceAudioCtx.createGain();
        voiceMuteGain.gain.value = 0;
        voiceBuffers = [];
        voiceCaptureKind = "script";

        voiceScriptNode.onaudioprocess = function (e) {
          if (!isRecording) { return; }
          var raw = e.inputBuffer.getChannelData(0);
          var copy = new Float32Array(raw.length);
          copy.set(raw);
          voiceBuffers.push(copy);
        };

        source.connect(voiceScriptNode);
        voiceScriptNode.connect(voiceMuteGain);
        voiceMuteGain.connect(voiceAudioCtx.destination);

        isRecording = true;

        function kickResume() {
          if (voiceAudioCtx && voiceAudioCtx.state === "suspended" && voiceAudioCtx.resume) {
            voiceAudioCtx.resume().catch(function () {});
          }
        }
        kickResume();
        setTimeout(kickResume, 0);

        if (voiceBtn) { voiceBtn.className = "btn-voice-hold recording"; }
        addMessage("system", "录音中，松手即可发送");
        appendLog("INFO", "ScriptProcessor 录音 采样率=" + voiceSampleRate);
      } catch (spErr) {
        appendLog("WARN", "ScriptProcessor 不可用，改用 MediaRecorder: " + String(spErr));
        try {
          if (voiceScriptNode) { voiceScriptNode.disconnect(); }
        } catch (e10) {}
        try {
          if (voiceMuteGain) { voiceMuteGain.disconnect(); }
        } catch (e11) {}
        voiceScriptNode = null;
        voiceMuteGain = null;
        isRecording = false;
        startMediaRecorderFromStream(stream);
      }
    }

    function onError(err) {
      voiceGumPending = false;
      try {
        if (voiceAudioCtx) { voiceAudioCtx.close(); }
      } catch (e12) {}
      voiceAudioCtx = null;
      appendLog("WARN", "麦克风错误: " + String(err));
      addMessage("system", "无法访问麦克风：请确认使用 https，并在设置中允许该网站使用麦克风");
    }

    var audioConstraints = { audio: true, video: false };

    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices.getUserMedia(audioConstraints).then(onStream).catch(onError);
      return;
    }

    var gum = navigator.getUserMedia      ||
              navigator.webkitGetUserMedia ||
              navigator.mozGetUserMedia    || null;

    if (!gum) {
      voiceGumPending = false;
      try {
        if (voiceAudioCtx) { voiceAudioCtx.close(); }
      } catch (e13) {}
      voiceAudioCtx = null;
      addMessage("system", "浏览器不支持 getUserMedia");
      appendLog("WARN", "getUserMedia / mediaDevices 均不可用");
      return;
    }

    gum.call(navigator, audioConstraints, onStream, onError);
  }

  function stopVoiceRecord() {
    // MediaRecorder 路径：stop 在 onstop 里异步编码发送
    if (voiceMediaRecorder && voiceMediaRecorder.state === "recording") {
      isRecording = false;
      if (voiceBtn) { voiceBtn.className = "btn-voice-hold"; }
      try {
        voiceMediaRecorder.stop();
      } catch (e14) {}
      return;
    }

    if (!isRecording) {
      return;
    }
    isRecording = false;
    voiceCaptureKind = "";

    if (voiceBtn) { voiceBtn.className = "btn-voice-hold"; }

    if (voiceScriptNode) { voiceScriptNode.disconnect(); voiceScriptNode = null; }
    if (voiceMuteGain) { try { voiceMuteGain.disconnect(); } catch (e15) {} voiceMuteGain = null; }
    if (voiceMediaStream) {
      stopVoiceTracks(voiceMediaStream);
      voiceMediaStream = null;
    }
    if (voiceAudioCtx) { try { voiceAudioCtx.close(); } catch (e16) {} voiceAudioCtx = null; }

    if (voiceBuffers.length === 0) {
      addMessage("system", "录音时间太短，请重试");
      return;
    }

    var totalLen = 0;
    var bi;
    for (bi = 0; bi < voiceBuffers.length; bi += 1) { totalLen += voiceBuffers[bi].length; }
    var merged = new Float32Array(totalLen);
    var mOff = 0;
    for (bi = 0; bi < voiceBuffers.length; bi += 1) {
      merged.set(voiceBuffers[bi], mOff);
      mOff += voiceBuffers[bi].length;
    }
    voiceBuffers = [];

    var pcm16 = new Int16Array(merged.length);
    var pi;
    for (pi = 0; pi < merged.length; pi += 1) {
      var s = Math.max(-1, Math.min(1, merged[pi]));
      pcm16[pi] = s < 0 ? Math.round(s * 32768) : Math.round(s * 32767);
    }

    var wavBytes = encodeWav(pcm16, voiceSampleRate);
    appendLog("INFO", "WAV 大小: " + wavBytes.length + " bytes，发送中...");
    sendVoiceWav(wavBytes);
  }

  // WAV 编码（RIFF/PCM，单声道 16bit）
  function encodeWav(pcm16, sampleRate) {
    var dataSize = pcm16.length * 2; // Int16 = 2 bytes
    var buf = new ArrayBuffer(44 + dataSize);
    var v = new DataView(buf);
    var i;
    var ws = function (off, str) {
      for (i = 0; i < str.length; i += 1) { v.setUint8(off + i, str.charCodeAt(i)); }
    };
    ws(0, "RIFF");
    v.setUint32(4,  36 + dataSize, true);
    ws(8, "WAVE");
    ws(12, "fmt ");
    v.setUint32(16, 16, true);         // PCM chunk size
    v.setUint16(20,  1, true);         // format: PCM
    v.setUint16(22,  1, true);         // channels: 1
    v.setUint32(24, sampleRate, true);
    v.setUint32(28, sampleRate * 2, true); // byte rate (sampleRate × 1ch × 2bytes)
    v.setUint16(32,  2, true);         // block align
    v.setUint16(34, 16, true);         // bits per sample
    ws(36, "data");
    v.setUint32(40, dataSize, true);
    var off = 44;
    for (i = 0; i < pcm16.length; i += 1) {
      v.setInt16(off, pcm16[i], true);
      off += 2;
    }
    return new Uint8Array(buf);
  }

  // 通过 AUDIO_INPUT_CHUNK + AUDIO_INPUT_END 发送 WAV 到服务器 ASR
  function sendVoiceWav(bytes) {
    if (!socket || socket.readyState !== 1) {
      addMessage("system", "未连接到服务器，语音未发送。请等顶部圆点变绿（已连接）后再试。");
      appendLog("WARN", "语音未发送：WebSocket 未连接");
      return;
    }
    var chunkSize = 32 * 1024;
    var total = Math.ceil(bytes.length / chunkSize);
    var trace = traceId("voice");
    var i;
    for (i = 0; i < total; i += 1) {
      var part = bytes.subarray(i * chunkSize, Math.min((i + 1) * chunkSize, bytes.length));
      safeSend("AUDIO_INPUT_CHUNK", {
        chunk_index: i,
        chunk_base64: uint8ToBase64(part),
        file_name: "voice.wav",
        mime_type: "audio/wav"
      }, trace);
    }
    safeSend("AUDIO_INPUT_END", { file_name: "voice.wav", chunks: total }, trace);
  }

  function initVoiceInput() {
    if (!voiceBtn) { return; }

    voiceBtn.title = "按住说话，松开发送（iPad 可先松手授权麦克风，再点一次结束）";

    function voicePointerDown(e) {
      e.preventDefault();
      unlockAudio();
      if (isRecording || (voiceMediaRecorder && voiceMediaRecorder.state === "recording")) {
        stopVoiceRecord();
        return;
      }
      startVoiceRecord();
    }

    function voicePointerUp(e) {
      e.preventDefault();
      if (isRecording && !voiceGumPending) {
        stopVoiceRecord();
      }
    }

    if (typeof window.PointerEvent !== "undefined") {
      voiceBtn.addEventListener("pointerdown", voicePointerDown, { passive: false });
      voiceBtn.addEventListener("pointerup", voicePointerUp, { passive: false });
      voiceBtn.addEventListener("pointercancel", voicePointerUp, { passive: false });
    } else {
      voiceBtn.addEventListener("touchstart", function (e) {
        e.preventDefault();
        if (isRecording) { stopVoiceRecord(); return; }
        startVoiceRecord();
      }, { passive: false });
      voiceBtn.addEventListener("touchend", function (e) {
        e.preventDefault();
        if (isRecording && !voiceGumPending) { stopVoiceRecord(); }
      }, { passive: false });
      voiceBtn.addEventListener("touchcancel", function (e) {
        e.preventDefault();
        if (isRecording && !voiceGumPending) { stopVoiceRecord(); }
      }, { passive: false });
      voiceBtn.addEventListener("mousedown", function () {
        if (isRecording) { stopVoiceRecord(); return; }
        startVoiceRecord();
      });
      voiceBtn.addEventListener("mouseup", stopVoiceRecord);
      voiceBtn.addEventListener("mouseleave", function () {
        if (isRecording) { stopVoiceRecord(); }
      });
    }
  }

  // ============================================================
  // 特效
  // ============================================================

  function playHeartEffect() {
    if (!heartEffect) { return; }
    heartEffect.className = "heart-effect run";
    setTimeout(function () { heartEffect.className = "heart-effect hidden"; }, 1100);
  }

  // ============================================================
  // QR 码
  // ============================================================

  function renderQRCode(payload) {
    var qrimg = payload.qrimg || "";
    var qrurl = payload.qrurl || "";
    if (qrImage) {
      if (qrimg) {
        qrImage.src = qrimg;
        qrImage.className = "qr-image";
      } else {
        qrImage.className = "qr-image hidden";
      }
    }
    if (qrText) {
      qrText.textContent = qrurl ? "二维码链接：" + qrurl : (qrimg ? "请扫码登录" : "二维码数据为空");
    }
  }

  // ============================================================
  // 天气 Overlay（左上角，最近3天）
  // ============================================================

  function renderWeatherOverlay(payload) {
    if (!weatherOverlay || !weatherCity || !weatherDays) { return; }

    var cityName = (payload.city || "") + " " + (payload.adm2 || payload.adm1 || "");
    weatherCity.textContent = cityName.trim();

    var forecast = payload.forecast || [];
    // 最多显示 3 天
    var days = forecast.slice(0, 3);

    while (weatherDays.firstChild) { weatherDays.removeChild(weatherDays.firstChild); }

    var labels = ["今天", "明天", "后天"];
    var i;
    for (i = 0; i < days.length; i += 1) {
      var d = days[i];
      var row = document.createElement("div");
      row.className = "weather-day-row";

      var lbl = document.createElement("div");
      lbl.className = "weather-day-label";
      lbl.textContent = labels[i] || d.date;

      var info = document.createElement("div");
      info.className = "weather-day-info";
      var cond = d.text_day || d.text_night || "";
      var temp = (d.temp_min || "?") + "~" + (d.temp_max || "?") + "°";
      info.textContent = cond + " " + temp;

      row.appendChild(lbl);
      row.appendChild(info);
      weatherDays.appendChild(row);
    }

    // 显示 overlay
    weatherOverlay.className = weatherOverlay.className.replace(" hidden", "").replace("hidden", "");
  }

  // ============================================================
  // 音频播放
  // ============================================================

  function unlockAudio() {
    if (audioUnlocked) { return; }
    audioUnlocked = true;
    audioUnlocking = true;
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) {
      if (!audioCtx) { audioCtx = new Ctx(); }
      if (audioCtx.state === "suspended" && audioCtx.resume) { audioCtx.resume(); }
    }
    try {
      audioPlayer.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAA==";
      audioPlayer.volume = 0;
      audioPlayer.load();
      var p = audioPlayer.play();
      if (p && typeof p.then === "function") {
        p.then(function () {
          audioPlayer.pause();
          audioPlayer.volume = 1;
          audioUnlocking = false;
        })["catch"](function () {
          audioPlayer.volume = 1;
          audioUnlocking = false;
        });
      } else {
        audioPlayer.volume = 1;
        audioUnlocking = false;
      }
    } catch (e) {
      audioPlayer.volume = 1;
      audioUnlocking = false;
    }
    appendLog("INFO", "音频播放已解锁");
  }

  function playAudio() {
    audioPlayer.load();
    var ret = audioPlayer.play();
    if (ret && typeof ret["catch"] === "function") {
      ret.then(function () {
        appendLog("INFO", "audioPlayer.play() 成功");
      })["catch"](function (err) {
        appendLog("WARN", "自动播放被阻止: " + String(err));
      });
    }
  }

  function stopAiTtsPlayback() {
    if (voicePlaybackSource) {
      try { voicePlaybackSource.stop(0); } catch (e) {}
      voicePlaybackSource = null;
    }
    try { audioPlayer.pause(); audioPlayer.currentTime = 0; } catch (e) {}
    if (ttsBlobUrl) {
      try { window.URL.revokeObjectURL(ttsBlobUrl); } catch (e) {}
      ttsBlobUrl = null;
    }
    stopMouthSync();
  }

  function renderAudio(payload) {
    var url = payload.url || "";
    if (!url) { return; }
    // 用 fragment 区分每次播放，避免 WebView 缓存同一 URL 而不重新 load（不改动 ? 查询串，免破坏签名）
    var baseUrl = url.split("#")[0];
    url = baseUrl + "#_padts=" + Date.now();
    ttsPlayGeneration += 1;
    stopAiTtsPlayback();
    try { unlockAudio(); } catch (e1) {}
    audioPlayer.src = url;
    if (audioText) { audioText.textContent = "播放地址：" + url; }
    playAudio();
  }

  // ============================================================
  // 口型动画（正弦波，兼容旧 WebView）
  // ============================================================

  function applyMouthValue(value) {
    var v = Math.max(0, Math.min(1, value));
    if (mouthBarInner) { mouthBarInner.style.width = String(Math.floor(v * 100)) + "%"; }
    window._live2dMouthValue = v;
  }

  function startMouthAnimation(durationMs) {
    stopMouthSync();
    var startTs = Date.now();
    function tick() {
      var elapsed = Date.now() - startTs;
      if (durationMs && elapsed >= durationMs) { applyMouthValue(0); mouthRaf = null; return; }
      var phase = elapsed / 1000 * 3 * 2 * 3.14159;
      applyMouthValue(Math.max(0, Math.sin(phase) * 0.6 + 0.1));
      mouthRaf = window.requestAnimationFrame(tick);
    }
    mouthRaf = window.requestAnimationFrame(tick);
  }

  function startMouthSync() { startMouthAnimation(0); }

  function stopMouthSync() {
    if (mouthRaf) { window.cancelAnimationFrame(mouthRaf); mouthRaf = null; }
    applyMouthValue(0);
  }

  // ============================================================
  // 音频流（MSE / AudioContext / FileReader 三重 fallback）
  // ============================================================

  function setupAudioStreaming() {
    useMse = false;
    sourceQueue = [];
    fallbackChunks = [];
    sourceBuffer = null;
    if (mediaSourceUrl) {
      try { window.URL.revokeObjectURL(mediaSourceUrl); } catch (e) {}
      mediaSourceUrl = null;
    }
    if (!window.MediaSource || !window.MediaSource.isTypeSupported("audio/mpeg")) { return; }
    mediaSource = new window.MediaSource();
    mediaSourceUrl = window.URL.createObjectURL(mediaSource);
    audioPlayer.src = mediaSourceUrl;
    mediaSource.addEventListener("sourceopen", function () {
      try {
        sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
        sourceBuffer.mode = "sequence";
        useMse = true;
        sourceBuffer.addEventListener("updateend", flushSourceQueue);
      } catch (err) {
        useMse = false;
        appendLog("WARN", "MSE 初始化失败，回退到缓存播放。");
      }
    });
  }

  function flushSourceQueue() {
    if (!sourceBuffer || sourceBuffer.updating || !sourceQueue.length) { return; }
    try { sourceBuffer.appendBuffer(sourceQueue.shift()); } catch (e) {
      appendLog("WARN", "MSE appendBuffer 失败: " + String(e));
      useMse = false; // 降级，下次用 fallback
    }
  }

  function base64ToUint8(b64) {
    var bin = window.atob(b64);
    var bytes = new Uint8Array(bin.length);
    var i;
    for (i = 0; i < bin.length; i += 1) { bytes[i] = bin.charCodeAt(i); }
    return bytes;
  }

  function onAudioChunk(payload) {
    var chunk = payload.chunk_base64 || "";
    if (!chunk) { return; }

    // 收到新音频第一个分片时，立即停止上一条 TTS（含 Web Audio 解码播放）
    var chunkIndex = typeof payload.chunk_index === "number" ? payload.chunk_index : 0;
    if (chunkIndex === 0) {
      ttsPlayGeneration += 1;
      stopAiTtsPlayback();
      fallbackChunks = [];
      sourceQueue = [];
      useMse = false;
      appendLog("INFO", "新音频到来，已中断旧播放");
    }

    var bytes = base64ToUint8(chunk);
    if (useMse && sourceBuffer) {
      sourceQueue.push(bytes);
      flushSourceQueue();
      return;
    }
    fallbackChunks.push(bytes);
  }

  function onAudioEnd(payload) {
    var totalChunks = payload.total_chunks || 0;
    if (audioText) { audioText.textContent = "收到分片：" + totalChunks; }
    if (useMse) {
      try { audioPlayer.currentTime = 0; } catch (e) {}
      playAudio();
      return;
    }
    if (!fallbackChunks.length) { return; }
    var totalLen = 0;
    var i;
    for (i = 0; i < fallbackChunks.length; i += 1) { totalLen += fallbackChunks[i].length; }
    var merged = new Uint8Array(totalLen);
    var offset = 0;
    for (i = 0; i < fallbackChunks.length; i += 1) {
      merged.set(fallbackChunks[i], offset);
      offset += fallbackChunks[i].length;
    }
    fallbackChunks = [];

    stopAiTtsPlayback();

    var gen = ttsPlayGeneration;
    var blob = new Blob([merged], { type: "audio/mpeg" });

    if (window.URL && window.URL.createObjectURL) {
      ttsBlobUrl = window.URL.createObjectURL(blob);
      audioPlayer.src = ttsBlobUrl;
      audioPlayer.load();
      var p = audioPlayer.play();
      if (p && typeof p.then === "function") {
        p.then(function () {
          appendLog("INFO", "播放 " + totalChunks + " 分片 (" + totalLen + " bytes)");
        })["catch"](function (err) {
          appendLog("WARN", "<audio> 播放失败: " + String(err) + "，尝试 Web Audio");
          playViaWebAudio(merged, gen);
        });
      } else {
        appendLog("INFO", "播放 " + totalChunks + " 分片 (" + totalLen + " bytes)");
      }
      return;
    }

    playWithFileReader(merged);
  }

  function playViaWebAudio(merged, gen) {
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) { playWithFileReader(merged); return; }
    if (!audioCtx) { audioCtx = new Ctx(); }
    if (audioCtx.state === "suspended" && audioCtx.resume) {
      audioCtx.resume()["catch"](function () {});
    }
    audioCtx.decodeAudioData(merged.buffer.slice(0), function (decoded) {
      if (gen !== ttsPlayGeneration) { return; }
      stopAiTtsPlayback();
      var src = audioCtx.createBufferSource();
      src.buffer = decoded;
      src.connect(audioCtx.destination);
      voicePlaybackSource = src;
      src.onended = function () {
        if (voicePlaybackSource === src) { voicePlaybackSource = null; }
        stopMouthSync();
      };
      src.start(0);
      startMouthAnimation(Math.ceil(decoded.duration * 1000));
      appendLog("INFO", "Web Audio 播放 " + decoded.duration.toFixed(1) + "s");
    }, function (err) {
      if (gen !== ttsPlayGeneration) { return; }
      appendLog("WARN", "Web Audio 解码失败: " + String(err) + "，尝试 FileReader");
      playWithFileReader(merged);
    });
  }

  function playWithFileReader(merged) {
    var gen = ttsPlayGeneration;
    var blob = new Blob([merged], { type: "audio/mpeg" });
    var reader = new FileReader();
    reader.onload = function () {
      if (gen !== ttsPlayGeneration) { return; }
      audioPlayer.src = reader.result;
      audioPlayer.load();
      audioPlayer.play()["catch"](function (err) {
        appendLog("ERROR", "FileReader 播放也失败: " + String(err));
      });
      appendLog("INFO", "FileReader 播放 (" + merged.length + " bytes)");
    };
    reader.onerror = function () { appendLog("ERROR", "FileReader 音频读取失败。"); };
    reader.readAsDataURL(blob);
  }

  // ============================================================
  // WebSocket 消息处理
  // ============================================================

  function onMessage(raw) {
    var data = null;
    try { data = JSON.parse(raw.data); } catch (e) { appendLog("RECV_RAW", raw.data); return; }

    var t = String(data.type || "").toUpperCase();
    var payload = data.payload || {};

    if (t === "ASR_RESULT") {
      appendLog("RECV ASR_RESULT", normalizeUserAsrText(payload) || "(空)");
    } else {
      appendLog("RECV " + t, data);
    }

    // 认证响应
    if (t === "AUTH_OK") {
      appendLog("INFO", "认证成功");
      addMessage("system", "✓ 已连接");
      // 认证后延迟 1s 自动请求天气卡片（WEATHER_QUERY 不走 AI，不产生聊天气泡）
      setTimeout(function () {
        if (socket && socket.readyState === 1) {
          appendLog("INFO", "自动加载天气...");
          safeSend("WEATHER_QUERY", { city: "武汉武昌" });
        }
      }, 1000);
      return;
    }
    if (t === "AUTH_FAILED") {
      appendLog("ERROR", "认证失败：" + (payload.message || "Token 错误"));
      addMessage("system", "✗ 认证失败，请在设置中检查 Token");
      return;
    }
    // UNAUTHORIZED：未认证就发了消息（通常是 ws_token 设置了但客户端未发 AUTH）
    if (t === "ERROR" && payload.code === "UNAUTHORIZED") {
      appendLog("WARN", "未认证，请在设置中填写正确的 Token");
      addMessage("system", "✗ 未认证，请点击右上角⚙️ → 填写 Token → 重新连接");
      return;
    }

    // TEXT：AI 回复文字（含镜像来的小智回复）
    if (t === "TEXT") {
      var txt = payload.text || "";
      // 区分来源：小智 bridge 推送时 payload 可能含 source 标记，否则视为本 AI
      var role = payload.source === "xiaozhi" ? "xiaozhi" : "ai";
      addMessage(role, txt);
      if (effectText) { effectText.textContent = txt; }
      return;
    }
    if (t === "QRCODE") { renderQRCode(payload); return; }
    if (t === "AUDIO_URL") { renderAudio(payload); return; }
    if (t === "AUDIO_CHUNK") { onAudioChunk(payload); return; }
    if (t === "AUDIO_END") { onAudioEnd(payload); return; }
    if (t === "WEATHER_CARD") { renderWeatherOverlay(payload); return; }
    if (t === "ASR_RESULT") {
      var asrTxt = normalizeUserAsrText(payload);
      if (asrTxt) { addMessage("user", asrTxt); }
      if (effectText) { effectText.textContent = asrTxt || ""; }
      return;
    }
    if (t === "MODEL_SWITCH") { loadModel(payload.model_id || "default", payload.style || ""); return; }
    if (t === "EFFECT") {
      if (effectText) { effectText.textContent = "特效：" + (payload.action || ""); }
      if (String(payload.action || "").toUpperCase() === "HEART") { playHeartEffect(); }
      return;
    }
    if (t === "ERROR") {
      var errMsg = "错误：" + (payload.message || "未知错误");
      addMessage("system", errMsg);
      if (effectText) { effectText.textContent = errMsg; }
    }
  }

  // ============================================================
  // WebSocket 连接管理
  // ============================================================

  function connect() {
    var wsUrl = wsUrlInput ? wsUrlInput.value.trim() : "";
    if (!wsUrl) { appendLog("WARN", "WebSocket 地址为空，无法连接。"); return; }
    if (socket) { socket.close(); }
    setupAudioStreaming();
    setStatus("连接中...", "connecting");
    socket = new WebSocket(wsUrl);

    socket.onopen = function () {
      isConnected = true;
      setStatus("已连接", "connected");
      appendLog("INFO", "WebSocket 连接成功");
      addMessage("system", "已连接 AI 助手");
      if (tokenInput && tokenInput.value) {
        safeSend("AUTH", { token: tokenInput.value }, traceId("auth"));
        // 保存 Token 到 localStorage，下次自动填充
        try { localStorage.setItem("ws_token", tokenInput.value); } catch (e) {}
        // 有 Token 时等 AUTH_OK 再查天气（在 AUTH_OK 处理中触发）
      } else {
        // 无 Token（服务器无鉴权要求），直接延迟请求天气卡片
        setTimeout(function () {
          if (socket && socket.readyState === 1) {
            appendLog("INFO", "自动加载天气（无鉴权）...");
            safeSend("WEATHER_QUERY", { city: "武汉武昌" });
          }
        }, 1000);
      }
      if (pingTimer) { clearInterval(pingTimer); }
      pingTimer = setInterval(function () {
        safeSend("PING", {}, traceId("heartbeat"));
      }, 20000);
    };

    socket.onmessage = onMessage;
    socket.onerror = function () {
      appendLog("ERROR", "WebSocket 发生错误（若页面是 https，地址须为 wss://当前域名/ws，不能填 ws://:8765）");
    };
    socket.onclose = function (ev) {
      isConnected = false;
      setStatus("已断开", "disconnected");
      var closeInfo = "WebSocket 连接关闭";
      if (ev && typeof ev.code === "number") {
        closeInfo += " code=" + ev.code + (ev.reason ? " reason=" + ev.reason : "");
      }
      appendLog("INFO", closeInfo);
      if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
      if (userRequestedDisconnect) { userRequestedDisconnect = false; return; }
      if (reconnectTimer) { clearTimeout(reconnectTimer); }
      reconnectTimer = setTimeout(function () {
        if (!isConnected) { connect(); }
      }, 3000);
    };
  }

  function disconnect() {
    userRequestedDisconnect = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); }
    if (socket) { socket.close(); socket = null; }
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    isConnected = false;
    setStatus("已断开", "disconnected");
  }

  // ============================================================
  // 发送文本
  // ============================================================

  function sendTextCommand() {
    var text = textInput ? (textInput.value || "").trim() : "";
    if (!text) { appendLog("WARN", "请输入文本指令。"); return; }
    addMessage("user", text);      // 立即在聊天记录显示用户消息
    safeSend("TEXT", { text: text });
    if (textInput) { textInput.value = ""; }
  }

  // ============================================================
  // 发送音频文件
  // ============================================================

  function uint8ToBase64(bytes) {
    var CHUNK = 0x8000;
    var index = 0;
    var result = "";
    while (index < bytes.length) {
      var slice = bytes.subarray(index, Math.min(index + CHUNK, bytes.length));
      var i; var bin = "";
      for (i = 0; i < slice.length; i += 1) { bin += String.fromCharCode(slice[i]); }
      result += window.btoa(bin);
      index += CHUNK;
    }
    return result;
  }

  function sendAudioInput() {
    if (!audioFileInput || !audioFileInput.files || !audioFileInput.files.length) {
      appendLog("WARN", "请先选择音频文件。"); return;
    }
    var file = audioFileInput.files[0];
    var reader = new FileReader();
    var trace = traceId("audio");
    reader.onload = function () {
      var bytes = new Uint8Array(reader.result);
      var chunkSize = 32 * 1024;
      var total = Math.ceil(bytes.length / chunkSize);
      var i;
      for (i = 0; i < total; i += 1) {
        var part = bytes.subarray(i * chunkSize, Math.min((i + 1) * chunkSize, bytes.length));
        safeSend("AUDIO_INPUT_CHUNK", {
          chunk_index: i, chunk_base64: uint8ToBase64(part),
          file_name: file.name, mime_type: file.type || "application/octet-stream"
        }, trace);
      }
      safeSend("AUDIO_INPUT_END", { file_name: file.name, chunks: total }, trace);
      if (audioUploadText) { audioUploadText.textContent = "已发送分片：" + total; }
    };
    reader.onerror = function () { appendLog("ERROR", "读取音频文件失败。"); };
    reader.readAsArrayBuffer(file);
  }

  // ============================================================
  // Live2D
  // ============================================================

  function initLive2D() {
    if (typeof L2Dwidget === "undefined" || typeof L2Dwidget.init !== "function") {
      appendLog("WARN", "L2Dwidget 未加载");
      if (modelText) { modelText.textContent = "Live2D 不可用"; }
      return false;
    }
    return true;
  }

  function loadModel(modelId, styleText) {
    if (!initLive2D()) { return; }
    var url = MODEL_URLS[modelId] || MODEL_URLS["default"];
    appendLog("INFO", "加载 Live2D: " + url);
    try {
      L2Dwidget.init({
        pluginRootPath: "./", pluginJsPath: "js/", pluginModelPath: "assets/",
        model: { jsonPath: url, scale: 1 },
        display: { position: "left", width: 180, height: 240, hOffset: 0, vOffset: 0 },
        mobile: { show: true, scale: 0.8 },
        react: { opacityDefault: 0.9, opacityOnHover: 0.2 }
      });
      live2dLoaded = true;
      if (modelText) { modelText.textContent = modelId + "（" + (styleText || "默认") + "）"; }
      appendLog("INFO", "L2Dwidget 初始化成功");
    } catch (e) {
      appendLog("ERROR", "L2Dwidget 异常: " + String(e));
    }
  }

  // Live2D 人物重定位：将 L2Dwidget 创建的浮动层移入容器
  function relocateLive2DWidget() {
    var widget = document.getElementById("live2d-widget");
    if (!widget) { setTimeout(relocateLive2DWidget, 600); return; }
    if (live2dContainer && widget.parentNode !== live2dContainer) {
      widget.style.position = "absolute";
      widget.style.bottom = "0";
      widget.style.left = "0";
      widget.style.right = "0";
      widget.style.margin = "0 auto";
      widget.style.top = "auto";
      live2dContainer.style.position = "relative";
      live2dContainer.appendChild(widget);
      appendLog("INFO", "Live2D 已嵌入容器");
    }
  }

  // ============================================================
  // 事件绑定
  // ============================================================

  if (connectBtn)    { connectBtn.onclick    = connect; }
  if (disconnectBtn) { disconnectBtn.onclick = disconnect; }
  if (sendTextBtn)   { sendTextBtn.onclick   = function () { unlockAudio(); sendTextCommand(); }; }
  if (sendAudioBtn)  { sendAudioBtn.onclick  = sendAudioInput; }
  if (textInput) {
    textInput.onkeydown = function (e) {
      if ((e.keyCode || e.which) === 13) { sendTextCommand(); }
    };
  }

  // 全局解锁：任意用户交互时解锁音频播放（iOS/Android autoplay policy）
  document.addEventListener("touchstart", unlockAudio, { once: true, passive: true });
  document.addEventListener("click", unlockAudio, { once: true, passive: true });

  audioPlayer.addEventListener("play", function () {
    if (audioUnlocking) { return; }
    startMouthSync();
  });
  audioPlayer.addEventListener("pause", function () {
    if (audioUnlocking) { return; }
    stopMouthSync();
  });
  audioPlayer.addEventListener("ended", function () {
    stopMouthSync();
    if (audioUnlocking) { audioUnlocking = false; return; }
    setTimeout(setupAudioStreaming, 200);
  });

  // ============================================================
  // 启动序列
  // ============================================================

  setStatus("未连接", "disconnected");

  // --- Token 自动加载（优先 URL 参数 ?token=xxx，其次 localStorage）---
  var autoToken = "";
  try {
    var urlSearch = window.location.search.slice(1).split("&");
    var ui;
    for (ui = 0; ui < urlSearch.length; ui += 1) {
      var pair = urlSearch[ui].split("=");
      if (pair[0] === "token" && pair[1]) {
        autoToken = decodeURIComponent(pair[1]);
        break;
      }
    }
    if (!autoToken) {
      autoToken = (window.localStorage && localStorage.getItem("ws_token")) || "";
    }
  } catch (e) {}
  if (autoToken && tokenInput) {
    tokenInput.value = autoToken;
    appendLog("INFO", "已自动加载 Token（来自" + (window.location.search.indexOf("token=") >= 0 ? "URL" : "本地存储") + "）");
  }

  // 设置面板关闭时保存 Token 到 localStorage
  if (settingsCloseBtn) {
    settingsCloseBtn.onclick = function () {
      closeSettings();
      if (tokenInput && tokenInput.value) {
        try { localStorage.setItem("ws_token", tokenInput.value); } catch (e) {}
      }
    };
  }

  var autoWsUrl = defaultWsUrlFromPage();
  if (wsUrlInput) { wsUrlInput.value = autoWsUrl; }

  appendLog("DIAG", [
    "JS版本: v20260406m",
    "L2Dwidget: " + typeof L2Dwidget,
    "FileReader: " + typeof window.FileReader,
    "AudioContext: " + typeof (window.AudioContext || window.webkitAudioContext),
    "SpeechAPI: " + typeof (window.SpeechRecognition || window.webkitSpeechRecognition),
    "MediaSource: " + typeof window.MediaSource,
    "WS: " + autoWsUrl,
    "UA: " + navigator.userAgent.slice(0, 60)
  ].join(" | "));

  applyInputMode(inputModeVoicePrimary);
  initVoiceInput();
  initLive2D();
  loadModel("default", "默认");

  window.addEventListener("resize", syncAppBodyBottom);
  setTimeout(syncAppBodyBottom, 200);

  setTimeout(function () {
    appendLog("INFO", "自动连接: " + autoWsUrl);
    connect();
  }, 1500);

  setTimeout(relocateLive2DWidget, 800);

})();
