(function () {
  function b64urlToBuf(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    const bin = atob(s);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }
  function bufToB64url(buf) {
    const bytes = new Uint8Array(buf);
    let s = "";
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function getCookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      body: body == null ? "" : JSON.stringify(body),
    });
    return r;
  }

  function toRegistrationCredential(cred) {
    const r = cred.response;
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(r.clientDataJSON),
        attestationObject: bufToB64url(r.attestationObject),
        transports: (r.getTransports && r.getTransports()) || [],
      },
      authenticatorAttachment: cred.authenticatorAttachment || null,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    };
  }

  function toAssertionCredential(cred) {
    const r = cred.response;
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64url(r.clientDataJSON),
        authenticatorData: bufToB64url(r.authenticatorData),
        signature: bufToB64url(r.signature),
        userHandle: r.userHandle ? bufToB64url(r.userHandle) : null,
      },
      authenticatorAttachment: cred.authenticatorAttachment || null,
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    };
  }

  async function register() {
    const btn = document.getElementById("pk-register");
    const status = document.getElementById("pk-status");
    const name = (document.getElementById("pk-name").value || "").trim();
    btn.disabled = true;
    status.textContent = "Requesting options…";
    try {
      const r = await postJSON("/passkeys/register/begin/");
      if (!r.ok) throw new Error(await r.text());
      const opts = await r.json();
      opts.challenge = b64urlToBuf(opts.challenge);
      opts.user.id = b64urlToBuf(opts.user.id);
      (opts.excludeCredentials || []).forEach((c) => (c.id = b64urlToBuf(c.id)));
      status.textContent = "Touch your authenticator…";
      const cred = await navigator.credentials.create({ publicKey: opts });
      status.textContent = "Verifying…";
      const finish = await postJSON("/passkeys/register/finish/", {
        credential: toRegistrationCredential(cred),
        name,
      });
      if (!finish.ok) throw new Error(await finish.text());
      status.textContent = "Registered. Reloading…";
      window.location.reload();
    } catch (e) {
      status.textContent = "Failed: " + (e.message || e);
      btn.disabled = false;
    }
  }

  async function login() {
    const status = document.getElementById("pk-login-status");
    try {
      if (status) status.textContent = "Requesting options…";
      const r = await postJSON("/passkeys/login/begin/");
      if (!r.ok) throw new Error(await r.text());
      const opts = await r.json();
      opts.challenge = b64urlToBuf(opts.challenge);
      (opts.allowCredentials || []).forEach((c) => (c.id = b64urlToBuf(c.id)));
      if (status) status.textContent = "Touch your authenticator…";
      const cred = await navigator.credentials.get({ publicKey: opts });
      if (status) status.textContent = "Verifying…";
      const finish = await postJSON("/passkeys/login/finish/", {
        credential: toAssertionCredential(cred),
      });
      const data = await finish.json();
      if (!finish.ok) throw new Error(data.error || "failed");
      window.location.assign(data.redirect || "/");
    } catch (e) {
      if (status) status.textContent = "Failed: " + (e.message || e);
    }
  }

  const regBtn = document.getElementById("pk-register");
  if (regBtn) regBtn.addEventListener("click", register);
  const loginBtn = document.getElementById("pk-login");
  if (loginBtn) loginBtn.addEventListener("click", login);
})();
