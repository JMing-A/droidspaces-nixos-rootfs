import pathlib

p = pathlib.Path('nix/base.nix')
s = p.read_text(encoding='utf-8')

start = s.index('      # sshd_config 的这些指令接受的是空格分隔的单个字符串。')
end = s.index('    };\n  };', start)

kex = [
    "curve25519-sha256",
    "curve25519-sha256@libssh.org",
    "ecdh-sha2-nistp256",
    "ecdh-sha2-nistp384",
    "ecdh-sha2-nistp521",
    "diffie-hellman-group-exchange-sha256",
    "diffie-hellman-group16-sha512",
    "diffie-hellman-group14-sha256",
]


def nix_list(name, items, indent='      '):
    body = '\n'.join(f'{indent}  "{i}"' for i in items)
    return f'{indent}{name} = [\n{body}\n{indent}];'


new_block = (
    '      # KexAlgorithms / Ciphers / Macs 在 nixpkgs 里被显式声明为\n'
    '      # nullOr (list of string)，传字符串会报 not of type list of string。\n'
    '      # 注意键名是 Macs，不是 MACs——写成 MACs 会落到未声明的 atom 类型上。\n'
    '      # 这三项在 sshd_config 里由 NixOS 自己用逗号拼接。\n'
    + nix_list('KexAlgorithms', kex) + '\n'
    + nix_list('Ciphers', [
        "chacha20-poly1305@openssh.com",
        "aes256-gcm@openssh.com",
        "aes128-gcm@openssh.com",
        "aes256-ctr",
        "aes192-ctr",
        "aes128-ctr",
    ]) + '\n'
    + nix_list('Macs', [
        "hmac-sha2-256-etm@openssh.com",
        "hmac-sha2-512-etm@openssh.com",
        "umac-128-etm@openssh.com",
        "hmac-sha2-256",
        "hmac-sha2-512",
    ]) + '\n'
)

s = s[:start] + new_block + s[end:]
p.write_text(s, encoding='utf-8')

assert 'MACs' not in s, 'stale MACs key remains'
assert 'Macs = [' in s
print('fixed: Macs as list of string')
print('braces', s.count('{') - s.count('}'), 'brackets', s.count('[') - s.count(']'))