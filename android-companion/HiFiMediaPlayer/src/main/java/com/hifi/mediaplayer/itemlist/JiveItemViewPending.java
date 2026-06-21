/*
 * Copyright (c) 2021 Kurt Aaholst <kaaholst@gmail.com>
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

package com.hifi.mediaplayer.itemlist;

import android.view.View;

import androidx.annotation.NonNull;

import com.hifi.mediaplayer.R;
import com.hifi.mediaplayer.framework.BaseActivity;
import com.hifi.mediaplayer.framework.ItemViewHolder;
import com.hifi.mediaplayer.model.JiveItem;
import com.hifi.mediaplayer.model.Window;

public class JiveItemViewPending extends ItemViewHolder<JiveItem> {

    private final boolean showIcon;
    private final View icon;

    JiveItemViewPending(@NonNull JiveItemListActivity activity, @NonNull View view) {
        this(activity, view, activity.window.windowStyle != Window.WindowStyle.TEXT_ONLY);
    }

    public JiveItemViewPending(@NonNull BaseActivity activity, @NonNull View view, boolean showIcon) {
        super(activity, view);
        icon = view.findViewById(R.id.icon);
        this.showIcon = showIcon;
    }

    @Override
    public void bindView(JiveItem item) {
        super.bindView(item);
        icon.setVisibility(showIcon ? View.VISIBLE : View.GONE);
    }

}
