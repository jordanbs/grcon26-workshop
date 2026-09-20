"use strict";

// The page holds one selection and asks the server to turn it into block
// parameters. It deliberately computes nothing itself: every string it
// shows came from iio_explain.annotate() or iio_grc.build(), both of
// which are tested without a browser.

const state = {
  capture: null,
  defaults: {buffer_size: 32768},
  device: null,            // annotated device dict
  channels: new Set(),     // channel ids to stream
  settings: new Map(),     // "chan:attr" -> {channel, attr, value}
  detail: null,
};

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// ------------------------------------------------------------ loading

fetch("/api/tree").then((r) => r.json()).then((payload) => {
  state.capture = payload.capture;
  state.defaults = payload.defaults;
  $("context").textContent =
    payload.source + " — " + (payload.capture.uri || "no uri") +
    " — " + (payload.capture.description || "");
  renderDevices();
  // Device 0 is xadc: the FPGA's own die temperature and supply rails. It
  // is the least relevant thing on the board and it was the landing page.
  // Open on something that actually carries samples.
  const first = state.capture.devices.find((d) => d.streaming) ||
                state.capture.devices[0];
  if (first) selectDevice(first);
});

// ------------------------------------------------------------ devices

function renderDevices() {
  // Only 5 of the M2K's 14 devices can carry samples. Listing all 14 flat,
  // in driver order, buries the ones a flowgraph can actually use.
  const host = $("devices");
  host.replaceChildren();

  const streams = state.capture.devices.filter((d) => d.streaming);
  const rest = state.capture.devices.filter((d) => !d.streaming);

  host.appendChild(deviceList(streams, "Carry samples"));
  if (rest.length) {
    const more = el("details");
    more.appendChild(el("summary", null,
      "Supporting devices (" + rest.length + ")"));
    more.appendChild(el("p", "hint",
      "No streaming channels, so no block of their own. Reach their " +
      "attributes with device_phy on a device that does stream."));
    more.appendChild(deviceList(rest, null));
    // Keep it open if the selection is in here, or choosing one would
    // slam the drawer on the thing you just picked.
    more.open = rest.some((d) => state.device && d.label === state.device.label);
    host.appendChild(more);
  }
}

function deviceList(devices, title) {
  const wrap = el("div", "devgroup");
  if (title) wrap.appendChild(el("h3", null, title));
  const list = el("ul");
  for (const device of devices) {
    const item = el("li");
    if (state.device && state.device.label === device.label) item.className = "on";
    item.appendChild(el("span", "name", device.label));
    item.appendChild(el("small", null, device.streaming
      ? device.streaming + " streaming of " + device.channels.length + " ch"
      : device.channels.length + " ch"));
    item.onclick = () => selectDevice(device);
    list.appendChild(item);
  }
  wrap.appendChild(list);
  return wrap;
}

function selectDevice(device) {
  // A Device Source targets one device, so the selection cannot outlive
  // a device change.
  state.device = device;
  // Tick the streaming channels to start with. Opening every device on
  // "No streaming channels selected. The block will have no outputs."
  // made the normal case look like an error, which teaches people to read
  // past warnings.
  state.channels = new Set(
    device.channels.filter((c) => c.scan_element).map((c) => c.id));
  state.settings = new Map();
  state.detail = null;
  clearDetail();
  renderDevices();
  renderContents();
  // Deliberately nothing open. While the explanation had a pane of its
  // own, opening one filled an empty column; inline it would bury the
  // rest of the device under the first channel's prose, and the shape of
  // the device is what you want on arrival.
  $("block").hidden = true;
  $("gen-copy").hidden = true;
  emit();
}

// ----------------------------------------------------------- contents

function renderContents() {
  const device = state.device;
  $("device-title").textContent = device.label;

  const note = $("device-note");
  note.replaceChildren();
  if (device.overlay) note.appendChild(overlayBlock(device.overlay));

  const host = $("contents");
  host.replaceChildren();

  const streaming = device.channels.filter((c) => c.scan_element);
  const config = device.channels.filter((c) => !c.scan_element);

  // An attribute promoted into Settings must not also render inline under
  // its channel: two controls writing one key drift apart the moment you
  // touch either of them.
  const promoted = new Set();
  for (const setting of device.settings || []) {
    if (setting.channels.length) {
      for (const id of setting.channels) promoted.add(id + "/" + setting.attr);
    } else {
      promoted.add("/" + setting.attr);
    }
  }

  // 1. What the block's ports will be. A sink consumes them, so calling
  // them outputs is wrong for half the devices on this board.
  const sink = device.streaming > 0 &&
    device.channels.filter((c) => c.scan_element).every((c) => c.output);
  if (streaming.length) {
    host.appendChild(channelGroup(
      "Streaming channels", streaming, true,
      sink
        ? "These become the inputs of the block, in this order."
        : "These become the outputs of the block, in this order.",
      promoted));
  }

  // 2. The knobs. Of 317 attributes on an M2K, 127 have a list of legal
  // values the hardware published -- those are the only ones that are
  // really settings. The rest are readings and state. Showing all of them
  // as identical editable rows said they were equally likely to matter.
  if (device.settings && device.settings.length) {
    host.appendChild(settingsGroup(device.settings));
  }

  // 3. Everything the two groups above did not already show, one click
  // away. Still editable -- this is a discovery tool, and hiding what the
  // hardware exposes would work against the point. Filtered so that every
  // attribute has exactly one control on the page: what is in Settings is
  // not repeated here, and the two together are the complete list.
  const rest = el("details", "rest");
  let count = 0;
  const inner = el("div");
  const notPromoted = (channelId) => (attr) =>
    !promoted.has(channelId + "/" + attr.name);

  if (config.length) {
    inner.appendChild(channelGroup(
      "Other channels", config, false,
      "No scan index, so they cannot stream. Their attributes still go " +
      "in Parameters.", promoted));
    count += config.reduce(
      (n, c) => n + c.attrs.filter(notPromoted(c.id)).length, 0);
  }
  for (const channel of streaming) {
    const left = channel.attrs.filter(notPromoted(channel.id));
    if (left.length) {
      inner.appendChild(attrGroup(channel.id, channel, left));
      count += left.length;
    }
  }
  for (const [key, title] of [["device_attrs", "Device attributes"],
                              ["buffer_attrs", "Buffer attributes"],
                              ["debug_attrs", "Debug attributes"]]) {
    const left = device[key].filter(notPromoted(""));
    if (left.length) {
      inner.appendChild(attrGroup(title, null, left));
      count += left.length;
    }
  }
  if (count) {
    rest.appendChild(el("summary", null,
      "Other attributes on this device (" + count + ")"));
    rest.appendChild(inner);
    host.appendChild(rest);
  }
}

// A setting the hardware published options for. One control may stand for
// the same attribute on many channels -- iio_grc.dropdown_attrs() does the
// collapsing, so the page and a generated block agree about what is one
// knob and what is eighteen.
function settingsGroup(settings) {
  const group = el("div", "group settings");
  group.appendChild(heading("Settings", settings.length));
  // A control can stand for the same attribute on many channels, so the
  // row count and the attribute count differ. Say so, or someone adding
  // up the two groups finds attributes missing.
  const covered = settings.reduce((n, s) => n + s.keys.length, 0);
  group.appendChild(el("p", "hint",
    covered === settings.length
      ? "The hardware published a list of legal values for these."
      : "The hardware published a list of legal values for these. " +
        settings.length + " controls covering " + covered + " attributes."));

  for (const setting of settings) {
    const row = el("div", "row");
    const label = el("span", "label", setting.label);
    const key = "s:" + setting.attr + ":" + setting.keys.join(",");
    row.dataset.key = key;
    label.onclick = () => toggleDetail(row, key, () => settingDetail(setting));
    row.appendChild(label);
    row.appendChild(el("span", "val", setting.value === null ||
      setting.value === undefined ? "" : String(setting.value)));
    // Which instrument this knob belongs to, when the vendor's own
    // library says. This is the difference between "an attribute" and
    // "the scope's input range".
    const use = setting.libm2k;
    if (use && use.instruments.length) {
      row.appendChild(el("span", "chip instrument", use.instruments[0]));
    }

    const select = el("select");
    const leave = el("option", null, "\u2014 leave alone \u2014");
    leave.value = "";
    select.appendChild(leave);
    for (const option of setting.options) {
      const node = el("option", null, option);
      node.value = option;
      select.appendChild(node);
    }
    // One control, but it may write several keys. Each key carries its own
    // channel so the sysfs prefix comes out right.
    select.onchange = () => {
      for (let i = 0; i < setting.keys.length; i++) {
        const key = setting.keys[i];
        if (select.value === "") state.settings.delete(key);
        else state.settings.set(key, {
          channel: setting.channels[i] || null,
          attr: setting.attr,
          value: select.value,
        });
      }
      emit();
    };
    row.appendChild(select);
    group.appendChild(row);

    if (setting.keys.length > 1) {
      group.appendChild(el("p", "hint",
        "applies to all " + setting.keys.length + " channels"));
    }
  }
  return group;
}

// A setting is one attribute wearing a collapsed label; explain the
// attribute it stands for.
function settingDetail(setting) {
  const device = state.device;
  const channelId = setting.channels[0];
  const channel = channelId
    ? device.channels.find((c) => c.id === channelId) : null;
  const pool = channel ? channel.attrs
    : device.device_attrs.concat(device.buffer_attrs, device.debug_attrs);
  const attr = pool.find((a) => a.name === setting.attr);
  return attr ? attrDetail(channel, attr) : null;
}

function channelGroup(title, channels, tickable, hint, promoted) {
  const group = el("div", "group");
  group.appendChild(heading(title, channels.length));
  if (hint) group.appendChild(el("p", "hint", hint));

  for (const channel of channels) {
    const row = el("div", "row");
    if (tickable) {
      const box = el("input");
      box.type = "checkbox";
      box.checked = state.channels.has(channel.id);
      box.onchange = () => {
        if (box.checked) state.channels.add(channel.id);
        else state.channels.delete(channel.id);
        emit();
      };
      row.appendChild(box);
    }
    const label = el("span", "label", channel.id +
      (channel.name && channel.name !== channel.id ? " (" + channel.name + ")" : ""));
    const key = "c:" + channel.id;
    row.dataset.key = key;
    label.onclick = () => toggleDetail(row, key, () => channelDetail(channel));
    row.appendChild(label);
    row.appendChild(el("span", "val",
      channel.output ? "output" : "input"));
    group.appendChild(row);

    const inline = (channel.attrs || []).filter(
      (a) => !(promoted && promoted.has(channel.id + "/" + a.name)));
    if (inline.length) {
      const nested = attrGroup(null, channel, inline);
      nested.style.marginLeft = tickable ? "1.4rem" : "0.8rem";
      group.appendChild(nested);
    }
  }
  return group;
}

function attrGroup(title, channel, attrs) {
  const group = el("div", "group");
  if (title) group.appendChild(heading(title, attrs.length));
  for (const attr of attrs) group.appendChild(attrRow(channel, attr));
  return group;
}

function heading(title, count) {
  const node = el("h3", null, title + " ");
  node.appendChild(el("span", "count", "(" + count + ")"));
  return node;
}

function attrRow(channel, attr) {
  const row = el("div", "row");
  const label = el("span", "label", attr.name);
  label.title = attr.sysfs_name;
  const key = "a:" + (channel ? channel.id : "") + ":" + attr.name;
  row.dataset.key = key;
  label.onclick = () => toggleDetail(row, key,
    () => attrDetail(channel, attr));
  row.appendChild(label);

  row.appendChild(el("span", "val",
    attr.read_error ? "unreadable" : (attr.value === null ? "" : attr.value)));

  row.appendChild(control(channel, attr));
  if (!attr.understood) row.appendChild(el("span", "chip", "unexplained"));
  return row;
}

// The control writes into `settings`; leaving it alone writes nothing.
// That matters: params it emits are attributes the flowgraph will write
// to the hardware on start, so "shown" must never mean "set".
function control(channel, attr) {
  const key = (channel ? channel.id : "") + ":" + attr.name;
  const current = state.settings.get(key);
  const available = attr.available;

  const apply = (value) => {
    if (value === "" || value === null) state.settings.delete(key);
    else state.settings.set(key, {
      channel: channel ? channel.id : null, attr: attr.name, value: value});
    emit();
  };

  if (available && available.kind === "options") {
    const select = el("select");
    select.appendChild(new Option("— leave alone —", ""));
    for (const value of available.values) select.appendChild(new Option(value, value));
    select.value = current ? current.value : "";
    select.onchange = () => apply(select.value);
    return select;
  }

  const input = el("input");
  input.type = "text";
  input.size = 8;
  input.placeholder = available && available.kind === "range"
    ? available.min + "–" + available.max
    : "leave alone";
  input.value = current ? current.value : "";
  input.onchange = () => apply(input.value.trim());
  return input;
}

// ------------------------------------------------------------- detail

function chips(provenance) {
  const wrap = el("div");
  for (const tag of provenance) {
    const [kind, confidence] = tag.split(":");
    const chip = el("span", "chip " + (confidence || kind),
      confidence ? "overlay: " + confidence : kind);
    wrap.appendChild(chip);
  }
  return wrap;
}

function overlayBlock(overlay) {
  const block = el("div", "overlay");
  block.appendChild(el("p", null, overlay.text));
  if (overlay.source) block.appendChild(el("p", "cite", "source: " + overlay.source));
  if (overlay.check) block.appendChild(el("p", "cite", "to verify: " + overlay.check));
  block.appendChild(chips(["overlay:" + overlay.confidence]));
  return block;
}

// The list and the explanation of what you clicked were two panes saying
// one thing. Now the explanation opens under its own row. One at a time,
// or a device with eighty attributes becomes a page you cannot scan.

let openPanel = null;
let openKey = null;

function toggleDetail(row, key, build) {
  if (openPanel) { openPanel.remove(); openPanel = null; }
  for (const other of document.querySelectorAll(".row.open")) {
    other.classList.remove("open");
  }
  if (openKey === key) { openKey = null; return; }

  const nodes = build();
  openKey = key;
  if (!nodes || !nodes.length) return;

  const panel = el("div", "inline-detail");
  panel.className = "detail inline-detail";
  for (const node of nodes) panel.appendChild(node);
  row.classList.add("open");
  row.after(panel);
  openPanel = panel;
}

function clearDetail() {
  if (openPanel) { openPanel.remove(); openPanel = null; }
  openKey = null;
}

function attrDetail(channel, attr) {
  const out = [];
  const title = el("p", "detail-title", attr.sysfs_name);
  out.push(title);
  out.push(el("p", "detail-where",
    state.device.label + (channel ? " / " + channel.id : "") +
    " — " + attr.type + " attribute"));
  out.push(chips(attr.provenance));

  if (attr.summary) {
    out.push(el("p", null, attr.summary));
    const dl = el("dl");
    addPair(dl, "its own unit", attr.unit);
    out.push(dl);
    if (attr.detail) out.push(el("p", null, attr.detail));
  } else {
    out.push(el("p", null,
      "Not in the ABI tables. Nothing generic is known about this " +
      "attribute — it is driver-specific."));
  }

  const facts = el("dl");
  addPair(facts, "value now", attr.read_error
    ? "unreadable (" + attr.read_error + ")"
    : (attr.value === null ? "—" : attr.value));
  if (attr.available) {
    addPair(facts, "legal values", attr.available.kind === "range"
      ? attr.available.min + " to " + attr.available.max +
        " step " + attr.available.step
      : attr.available.values.join(" "));
  }
  for (const [label, key] of [["direction", "direction"],
                              ["channel type", "channel_type"],
                              ["channel index", "channel_index"],
                              ["modifier", "modifier"]]) {
    if (attr.parsed[key] !== null && attr.parsed[key] !== undefined) {
      addPair(facts, label, String(attr.parsed[key]));
    }
  }
  addPair(facts, "role", attr.info_word);
  out.push(facts);

  if (attr.channel_type) {
    out.push(el("p", null,
      "Channel type '" + attr.channel_type.type + "' measures " +
      attr.channel_type.quantity + ". After scale and offset the unit is " +
      attr.channel_type.unit + "." +
      (attr.channel_type.note ? " Watch out: " + attr.channel_type.note + "." : "")));
  }

  if (attr.abi) {
    const block = el("div", "kernel");
    block.appendChild(el("h3", null, "The kernel's own words"));
    for (const paragraph of attr.abi.paragraphs) {
      block.appendChild(el("p", null, paragraph));
    }
    block.appendChild(el("p", "cite",
      "— Linux ABI " + attr.abi.source + ", since kernel " +
      (attr.abi.kernel_version || "?")));
    out.push(block);
  }

  // Independent of whether a board pack has anything to say: plenty of
  // attributes libm2k drives have no overlay note, and those are exactly
  // the ones where knowing the instrument is the only handle you get.
  if (attr.libm2k) {
    out.push(el("h3", null, "What drives it"));
    if (attr.libm2k.instruments.length) {
      out.push(el("p", null,
        "Part of the " + attr.libm2k.instruments.join(" and ").toLowerCase() +
        ". A knob you already know from Scopy, under its sysfs name."));
    }
    out.push(el("p", "hint",
      "libm2k reaches it from " + attr.libm2k.methods.slice(0, 3).join(", ")));
    out.push(chips(["libm2k"]));
  }

  if (attr.overlay) {
    const block = overlayBlock(attr.overlay);
    block.insertBefore(el("h3", null, "On this board"), block.firstChild);
    out.push(block);
  }

  return out;
}

function channelDetail(channel) {
  const out = [];
  out.push(el("p", "detail-title", channel.id));
  out.push(el("p", "detail-where", state.device.label + " — " +
    (channel.output ? "output" : "input") +
    (channel.scan_element
      ? ", streams at scan index " + channel.scan_index
      : ", not a scan element")));
  if (channel.description) out.push(el("p", null, channel.description));

  if (channel.data_format) {
    out.push(el("h3", null, "On the wire"));
    out.push(el("p", "mono", channel.data_format.shorthand));
    out.push(el("p", null, channel.data_format.english));
  }

  if (channel.identity && channel.identity.length) {
    out.push(el("h3", null, "What it is connected to"));
    // The last finding is the ABI convention, worth showing only when
    // nothing better answered -- same rule the CLI uses.
    const strong = channel.identity.filter((f) => !f.fallback);
    for (const finding of (strong.length ? strong : channel.identity)) {
      const block = el("div", finding.provenance === "overlay" ? "overlay" : null);
      block.appendChild(el("p", null, finding.text));
      block.appendChild(chips([finding.provenance === "overlay"
        ? "overlay:" + finding.confidence : finding.provenance]));
      out.push(block);
    }
  }

  if (channel.conversion) {
    const conv = channel.conversion;
    out.push(el("h3", null, "Raw to real"));
    if (conv.note) {
      out.push(el("p", null, conv.note));
    } else {
      out.push(el("p", "mono", conv.expression + " = " +
        conv.value + " " + (conv.symbol || "")));
      if (conv.si_value !== null && conv.si_value !== undefined) {
        out.push(el("p", "mono", "= " + conv.si_value + " " +
          (conv.si_symbol || "")));
      }
    }
    if (conv.streaming && conv.scale !== null && conv.scale !== undefined) {
      out.push(el("p", null,
        "The same contract still applies, one sample at a time:"));
      out.push(el("p", "mono", conv.offset !== null && conv.offset !== undefined
        ? "real = (sample + " + conv.offset + ") * " + conv.scale
        : "real = sample * " + conv.scale));
    }
    // The board's own recipe, for a device that publishes no scale at all.
    // This is the whole counts-to-volts answer for an M2K scope input, so
    // it must not be the one thing the page leaves out.
    if (conv.recipe) {
      const box = el("div", "overlay");
      box.appendChild(el("pre", "make", conv.recipe.text));
      box.appendChild(chips(["overlay:" + conv.recipe.confidence]));
      if (conv.recipe.source) {
        box.appendChild(el("p", "hint", "source: " + conv.recipe.source));
      }
      out.push(box);
    }
  }

  return out;
}

function addPair(dl, term, value) {
  if (value === null || value === undefined || value === "") return;
  dl.appendChild(el("dt", null, term));
  dl.appendChild(el("dd", null, String(value)));
}

// --------------------------------------------------------------- emit

let pending = null;

function emit() {
  if (!state.device) return;
  const selection = {
    device: state.device.label,
    channels: [...state.channels],
    settings: [...state.settings.values()],
    buffer_size: state.defaults.buffer_size,
    decimation: 1,
  };
  clearTimeout(pending);
  pending = setTimeout(() => {
    fetch("/api/emit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(selection),
    }).then((r) => r.json()).then(renderEmit);
  }, 60);
}

function renderEmit(result) {
  const host = $("emit");
  host.replaceChildren();
  for (const field of result.fields_display || []) {
    const wrap = el("div", "field");
    // The wide fields -- the ones holding Python lists -- are picked out
    // by id in the stylesheet so they get more of the row.
    wrap.dataset.id = field.id;
    const label = el("label", null, field.label + "  ");
    label.appendChild(el("span", "kind", field.kind));
    wrap.appendChild(label);
    const box = el("div", "box");
    const input = el("input");
    input.readOnly = true;
    input.value = field.text;
    box.appendChild(input);
    const button = el("button", null, "copy");
    button.onclick = () => copy(input, button);
    box.appendChild(button);
    wrap.appendChild(box);
    host.appendChild(wrap);
  }

  const warnings = $("warnings");
  warnings.replaceChildren();
  for (const message of result.warnings || []) {
    warnings.appendChild(el("div", "warn", message));
  }

  $("make").textContent = result.make || "";
  // A sink is a different block with different fields; say which one the
  // numbers below belong to rather than always claiming Device Source.
  const block = result.is_sink ? "IIO Device Sink" : "IIO Device Source";
  $("emit-title").textContent = "Your block parameters — " + block;
  $("emit-hint").textContent =
    "Type these into the " + block + " block in GRC. String fields take " +
    "bare text — no quotes. Raw fields take a Python literal.";
}

function copy(input, button) {
  const done = () => {
    button.textContent = "copied";
    setTimeout(() => { button.textContent = "copy"; }, 1200);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(input.value).then(done);
  } else {
    input.select();
    document.execCommand("copy");
    done();
  }
}


// ------------------------------------------------- generated GRC block

// Rung 3: the dropdowns the page shows can be baked into a block
// definition, because a GRC block is just a YAML file and the legal
// values are in the capture. GRC picks it up through GRC_BLOCKS_PATH.

$("gen").onclick = () => {
  if (!state.device) return;
  fetch("/api/block?device=" + encodeURIComponent(state.device.label))
    .then((r) => r.json())
    .then((payload) => {
      const pre = $("block");
      pre.hidden = false;
      pre.textContent = payload.error
        ? payload.error
        : "# " + payload.filename + "\n\n" + payload.yaml;
      const copy = $("gen-copy");
      copy.hidden = !!payload.error;
      copy.onclick = () => {
        navigator.clipboard.writeText(payload.yaml);
        copy.textContent = "copied";
        setTimeout(() => { copy.textContent = "copy"; }, 1200);
      };
    });
};
