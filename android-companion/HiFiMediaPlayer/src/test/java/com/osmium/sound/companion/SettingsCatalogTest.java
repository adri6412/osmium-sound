package com.osmium.sound.companion;

import junit.framework.TestCase;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The Settings tiles follow the kiosk's Settings (native-ui-qt SettingsTab.qml):
 * the same six macro groups, in the same order, and no empty group.
 */
public class SettingsCatalogTest extends TestCase {

    public void testGroupsFollowTheKioskOrder() {
        List<String> ids = new ArrayList<>();
        for (SettingsCatalog.Group g : SettingsCatalog.GROUPS) ids.add(g.id);
        assertEquals(Arrays.asList("music", "sound", "look", "control", "network", "system"), ids);
    }

    public void testEveryGroupHasSectionsAndUniqueSectionIds() {
        Set<String> seen = new HashSet<>();
        for (SettingsCatalog.Group g : SettingsCatalog.GROUPS) {
            assertFalse("group " + g.id + " has no sections", g.sections.isEmpty());
            for (SettingsCatalog.Section s : g.sections) {
                assertTrue("duplicate section id " + s.id, seen.add(s.id));
            }
        }
    }

    public void testEverySectionOpensExactlyOneThing() {
        for (SettingsCatalog.Group g : SettingsCatalog.GROUPS) {
            for (SettingsCatalog.Section s : g.sections) {
                boolean screen = s.launcher != null;
                boolean leaf = s.prefsKey != null;
                assertTrue("section " + s.id + " must open a screen or a preference leaf", screen ^ leaf);
            }
        }
    }

    public void testApplianceOnlySectionsAreHiddenOnAPlainLyrion() {
        for (SettingsCatalog.Group g : SettingsCatalog.GROUPS) {
            for (SettingsCatalog.Section s : g.visibleSections(false)) {
                assertFalse("appliance section " + s.id + " shown on a plain Lyrion server", s.applianceOnly);
            }
            assertEquals(g.sections.size(), g.visibleSections(true).size());
        }
    }

    public void testGroupLookupById() {
        assertNotNull(SettingsCatalog.group("look"));
        assertNull(SettingsCatalog.group("nope"));
    }
}
