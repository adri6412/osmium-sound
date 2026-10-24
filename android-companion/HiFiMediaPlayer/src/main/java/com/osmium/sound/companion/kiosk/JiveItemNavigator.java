/*
 * Copyright (c) 2026 Osmium Sound
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package com.osmium.sound.companion.kiosk;

import androidx.annotation.Nullable;

import com.osmium.sound.companion.model.Action;
import com.osmium.sound.companion.model.JiveItem;

/**
 * Implemented by the kiosk shell ({@link MainActivity}) so a drill-down pushes another browse level
 * into the shell's single content container (with the breadcrumb, tab bar and mini player staying
 * put) instead of starting a new {@code JiveItemListActivity}. Row views keep calling the static
 * {@code JiveItemListActivity.show(...)}; it routes here when the host is the shell.
 */
public interface JiveItemNavigator {

    /** Pushes a new browse level for {@code parent}/{@code action} onto the shell's back stack. */
    void pushBrowse(JiveItem parent, @Nullable Action action);

    /** Pushes the server-driven home menu level under {@code node} onto the shell's back stack. */
    void pushHomeMenu(JiveItem node);
}
