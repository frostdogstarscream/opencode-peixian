"""No known credential prefix is released while assistant text is incomplete."""
from control.app import public_messages, _secret_prefix_suffix

SECRET = "TEST-CREDENTIAL-123"
DISPLAYS = {"synthetic": {"_secrets": [SECRET]}}


def public(text, *, done=False, aborted=False, role="assistant", displays=DISPLAYS):
    info = {"id": "message", "sessionID": "session", "role": role, "time": {"created": 1}}
    if done:
        info["time"]["completed"] = 2
    if aborted:
        info["error"] = {"name": "MessageAbortedError"}
    values = [{"info": info, "parts": [{"id": "part", "messageID": "message", "sessionID": "session",
                                      "type": "text", "text": text}]}]
    result = public_messages(values, displays)[0]["parts"][0]["text"]
    assert values[0]["parts"][0]["text"] == text
    return result


def test_every_incremental_secret_prefix_is_held_then_complete_value_is_masked():
    observed = []
    for end in range(1, len(SECRET)):
        observed.append(public("Status: " + SECRET[:end]))
    assert observed == ["Status: "] * (len(SECRET) - 1)
    assert public("Status: " + SECRET) == "Status: [已隐藏凭据]"
    assert public("Status: " + SECRET, done=True) == "Status: [已隐藏凭据]"
    assert all(SECRET not in value for value in observed)


def test_nonmatching_continuation_restores_ordinary_text_without_state_loss():
    prefix = "TEST-CREDENTIAL-"
    assert public("Status: " + prefix) == "Status: "
    different = "Status: " + prefix + "XYZ"
    assert public(different) == different
    assert public(different, done=True) == different


def test_multiple_values_choose_longest_overlapping_suffix_and_mask_all_complete_values():
    secrets = {"synthetic": {"_secrets": ["LONG-TOKEN-123", "TOKEN-456", "ababa"]}}
    assert public("Status: LONG-TOKEN-", displays=secrets) == "Status: "
    text = "LONG-TOKEN-123 and TOKEN-456 and ababa"
    assert public(text, displays=secrets) == "[已隐藏凭据] and [已隐藏凭据] and [已隐藏凭据]"
    assert public(text, done=True, displays=secrets) == "[已隐藏凭据] and [已隐藏凭据] and [已隐藏凭据]"


def test_abort_does_not_release_a_previously_withheld_credential_prefix():
    prefix = "TEST-CREDENTIAL-"
    assert public("Status: " + prefix, aborted=True) == "Status: "
    assert public("Status: " + prefix, done=True, aborted=True) == "Status: "
    assert public("Status: " + SECRET, done=True, aborted=True) == "Status: [已隐藏凭据]"


def test_completed_nonsecret_suffix_and_user_text_are_not_indefinitely_held():
    prefix = "TEST-CREDENTIAL-"
    assert public("Status: " + prefix, done=True) == "Status: " + prefix
    assert public("Status: " + prefix, role="user") == "Status: " + prefix
    assert public("ordinary response") == "ordinary response"
    assert public("x", displays={"synthetic": {"_secrets": ["", None, "x"]}}) == "[已隐藏凭据]"


def test_kmp_handles_repeated_prefixes_and_unicode():
    assert _secret_prefix_suffix("start abababa", "abababac") == 7
    assert _secret_prefix_suffix("start abababz", "abababac") == 0
    assert _secret_prefix_suffix("说明：合成密钥", "合成密钥完整值") == len("合成密钥")
    assert _secret_prefix_suffix("", "secret") == 0
    assert _secret_prefix_suffix("text", "x") == 0


def test_long_repeated_prefix_uses_linear_character_work():
    class Counted(str):
        def __new__(cls, value, counter):
            result = super().__new__(cls, value)
            result.counter = counter
            return result

        def __getitem__(self, key):
            result = super().__getitem__(key)
            self.counter[0] += len(result) if isinstance(key, slice) else 1
            return Counted(result, self.counter) if isinstance(key, slice) else result

    size = 20000
    counter = [0]
    secret = Counted("a" * size + "b", counter)
    assert _secret_prefix_suffix("safe " + "a" * size, secret) == size
    assert counter[0] < 12 * size
