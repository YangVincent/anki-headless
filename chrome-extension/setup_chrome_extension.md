# Anki Quick Add — Chrome Extension Setup

## Install

1. Open `chrome://extensions` in Chrome
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `chrome-extension/` folder

## Configure

1. Click the extension icon in the toolbar → three dots → **Options**
2. Paste your API key: `UphTte9DKEh5KVg0pW7Al-DALuhjh1NWW3gves77FpM`
3. Click **Save**

## Usage

**Right-click method:** Select Chinese text on any page → right-click → **Add to Anki**

**Popup method:** Click the extension icon → type a word → press Enter or click **Add**

The badge on the icon shows status:
- `...` — processing
- `OK` — card created/improved
- `ERR` — something went wrong
- `KEY` — API key not set (go to options)

## API endpoint

`POST https://anki.aeonneo.com/api/card`

```
Authorization: Bearer <api_key>
Content-Type: application/json

{"word": "学习", "context": "optional sentence context"}
```

Returns:
```json
{"status": "created", "word": "学习", "pinyin": "xuéxí", "meaning": "to learn, to study", "action_details": "..."}
```
