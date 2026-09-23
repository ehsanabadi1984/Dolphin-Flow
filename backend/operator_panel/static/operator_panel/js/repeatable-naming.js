function reindexRepeatableFieldName(oldName, groupPrefix, newIndex) {
    if (!oldName.startsWith(groupPrefix)) {
        return oldName;
    }

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

globalThis.DolphinFlowRepeatableNaming = {
    reindexRepeatableFieldName,
};
