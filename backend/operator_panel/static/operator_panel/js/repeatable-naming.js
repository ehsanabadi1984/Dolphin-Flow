function reindexRepeatableFieldName(
    oldName,
    groupPrefix,
    newIndex,
    groupCode = null,
) {
    if (oldName.startsWith(groupPrefix)) {
        const remainder = oldName.slice(groupPrefix.length);
        const separatorIndex = remainder.indexOf("_");

        if (separatorIndex === -1) {
            return oldName;
        }

        return (
            groupPrefix +
            String(newIndex) +
            remainder.slice(separatorIndex)
        );
    }

    /*
     * A nested repeatable template can be cloned from a real parent row.
     * Its template name then contains the source parent's path, e.g.
     * parents_0_children_TEMPLATE_name, while the new row may need
     * parents_1_children_0_name.
     */
    if (groupCode) {
        const templateMarker = `_${groupCode}_TEMPLATE_`;
        const markerIndex = oldName.lastIndexOf(templateMarker);

        if (markerIndex !== -1) {
            return (
                groupPrefix +
                String(newIndex) +
                oldName.slice(markerIndex + templateMarker.length)
            );
        }

        const rootTemplateMarker = `${groupCode}_TEMPLATE_`;
        if (oldName.startsWith(rootTemplateMarker)) {
            return (
                groupPrefix +
                String(newIndex) +
                oldName.slice(rootTemplateMarker.length)
            );
        }
    }

    return oldName;
}
function buildRepeatableGroupPrefix(parentContext, groupCode) {
    return (
        parentContext
            .map(({ groupCode, index }) => `${groupCode}_${index}_`)
            .join("") +
        groupCode +
        "_"
    );
}

globalThis.DolphinFlowRepeatableNaming = {
    reindexRepeatableFieldName,
    buildRepeatableGroupPrefix,
};
