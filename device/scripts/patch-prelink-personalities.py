#!/usr/bin/env python3
"""Drop IOKit personalities from the prelinked kext metadata of kernel.macho.

The prelink step copies Apple kexts of the qualified kernelcache into
__PRELINK_INFO.  A driver qualified for Apple silicon can still match a node of
the virtual board and start against hardware that does not exist here:
com.apple.driver.AppleARMPlatform's AppleARMCPU personality (IOProviderClass
IOPlatformDevice, IONameMatch "cpu") is started on the virtual /cpus nodes and
panics with "CPU configuration in device tree is invalid".

This tool removes the named personality from its kext entry while keeping every
other byte of the metadata and the whole Mach-O geometry untouched: the XML is
edited in place, the leftover space is zero-filled, and the result is parsed
back and compared against the original metadata before it is written.

Usage:
    patch-prelink-personalities.py --kernel kernel.macho \
        --drop com.apple.driver.AppleARMPlatform:AppleARMCPU [--drop ...] [--list]
"""
import argparse
import copy
import plistlib
import struct
from pathlib import Path

PRELINK_SEGMENT = b'__PRELINK_INFO'
PRELINK_SECTION = b'__info'
CONTAINERS = ('dict', 'array')


class Node:
    """One XML element with the byte span it occupies in the section."""

    def __init__(self, data, tag, start):
        self.data, self.tag, self.start, self.end = data, tag, start, start
        self.children, self.text_span = [], None

    @property
    def text(self):
        start, end = self.text_span
        return self.data[start:end].decode('utf-8', 'replace')


def parse_element(data, pos):
    """Parse the element that starts at data[pos] == '<'; return (Node, next_pos)."""
    if data[pos:pos + 1] != b'<':
        raise ValueError(f'expected an element at {pos}')
    close = data.index(b'>', pos)
    header = data[pos + 1:close]
    if header.endswith(b'/'):
        node = Node(data, header[:-1].split()[0].decode(), pos)
        node.end = close + 1
        return node, close + 1
    tag = header.split()[0].decode()
    node = Node(data, tag, pos)
    body = close + 1
    if tag in CONTAINERS:
        cursor = body
        while data[cursor:cursor + 2] != b'</':
            child, cursor = parse_element(data, cursor)
            node.children.append(child)
        end = data.index(b'>', cursor)
        if data[cursor + 2:end] != tag.encode():
            raise ValueError(f'unexpected close tag at {cursor}')
        node.end = end + 1
        return node, end + 1
    end_tag = b'</' + tag.encode() + b'>'
    end = data.index(end_tag, body)
    node.text_span = (body, end)
    node.end = end + len(end_tag)
    return node, node.end


def dict_pairs(node):
    """(key text, key node, value node) triples of a parsed <dict>."""
    if node.tag != 'dict' or len(node.children) % 2:
        raise ValueError('a plist dict needs key/value pairs')
    pairs = []
    for index in range(0, len(node.children), 2):
        key, value = node.children[index], node.children[index + 1]
        if key.tag != 'key':
            raise ValueError('expected a <key> element')
        pairs.append((key.text, key, value))
    return pairs


def find_pair(node, name):
    for key, key_node, value_node in dict_pairs(node):
        if key == name:
            return key_node, value_node
    return None


def load_section(image):
    """Return (file offset, size) of __PRELINK_INFO,__info."""
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from('<IiiIIIII', image, 0)
    if magic != 0xFEEDFACF:
        raise ValueError('not a thin 64-bit little-endian Mach-O')
    offset = 32
    for _ in range(ncmds):
        command, length = struct.unpack_from('<II', image, offset)
        if command == 0x19:
            nsects = struct.unpack_from('<I', image, offset + 64)[0]
            section = offset + 72
            for _ in range(nsects):
                name = image[section:section + 16].split(b'\0')[0]
                segment = image[section + 16:section + 32].split(b'\0')[0]
                size, fileoff = struct.unpack_from('<QI', image, section + 40)
                if name == PRELINK_SECTION and segment == PRELINK_SEGMENT:
                    return fileoff, size
                section += 80
        offset += length
    raise ValueError('no __PRELINK_INFO,__info section')


def parse_metadata(section):
    start = section.find(b'<dict>')
    end = section.rfind(b'</dict>')
    if start < 0 or end < 0:
        raise ValueError('section carries no plist dictionary')
    return plistlib.loads(b'<plist version="1.0">' + section[start:end + 7] + b'</plist>')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--kernel', required=True, type=Path, help='kernel.macho to edit in place')
    parser.add_argument('--drop', action='append', default=[], metavar='BUNDLE:PERSONALITY',
                        help='kext identifier and IOKit personality name to remove')
    parser.add_argument('--list', action='store_true', help='print every kext personality and exit')
    args = parser.parse_args()

    image = bytearray(args.kernel.read_bytes())
    fileoff, size = load_section(image)
    section = bytes(image[fileoff:fileoff + size])
    before = parse_metadata(section)
    root, _ = parse_element(section, section.find(b'<dict>'))
    entries = before['_PrelinkInfoDictionary']

    if args.list:
        for entry in entries:
            names = sorted(entry.get('IOKitPersonalities') or {})
            if names:
                print(f'{entry.get("CFBundleIdentifier")}: {", ".join(names)}')
        return 0

    if not args.drop:
        parser.error('nothing to do: pass --drop BUNDLE:PERSONALITY or --list')

    removals = []
    for request in args.drop:
        identifier, separator, personality = request.partition(':')
        if not separator or not identifier or not personality:
            parser.error(f'--drop needs BUNDLE:PERSONALITY, got {request}')
        entry_node = None
        for candidate in find_pair(root, '_PrelinkInfoDictionary')[1].children:
            bundle = find_pair(candidate, 'CFBundleIdentifier')
            if bundle and bundle[1].text == identifier:
                entry_node = candidate
                break
        if entry_node is None:
            raise SystemExit(f'no prelinked kext {identifier}')
        personalities = find_pair(entry_node, 'IOKitPersonalities')
        if personalities is None:
            raise SystemExit(f'{identifier} carries no IOKitPersonalities')
        pair = find_pair(personalities[1], personality)
        if pair is None:
            print(f'{identifier}:{personality} already absent')
            continue
        removals.append((identifier, personality, pair[0].start, pair[1].end))

    if not removals:
        print(f'{args.kernel}: nothing to do, metadata already clean')
        return 0

    edited = bytearray(section)
    for identifier, personality, start, end in sorted(removals, key=lambda item: item[2], reverse=True):
        del edited[start:end]
        print(f'removed {identifier}:{personality} ({end - start} bytes)')

    if len(edited) + 1 > size:
        raise SystemExit('the edited metadata does not fit its section')
    rebuilt = bytes(edited) + bytes(size - len(edited))

    # The removed personalities must be the only difference, and the section
    # must keep its exact size so no Mach-O offset moves.
    expected = copy.deepcopy(before)
    for identifier, personality, _, _ in removals:
        entry = next(item for item in expected['_PrelinkInfoDictionary']
                     if item.get('CFBundleIdentifier') == identifier)
        entry['IOKitPersonalities'].pop(personality)
        if not entry['IOKitPersonalities']:
            del entry['IOKitPersonalities']
    after = parse_metadata(rebuilt)
    if after != expected:
        raise SystemExit('metadata differs beyond the removed personalities; nothing written')

    image[fileoff:fileoff + size] = rebuilt
    args.kernel.write_bytes(image)
    print(f'{args.kernel}: {len(removals)} personality(ies) removed, section kept at {size} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
