import {html, render} from 'https://unpkg.com/lit-html?module';

const intBool = value => value ? 1 : 0;

const contactTemplate = (data) => html`
    <a class="contact" title="${data.type}: ${data.contact}" href="${data.href}"
            target="_blank"
            data-onlyicon="${data.onlyicon||0}"
            data-icon="${data.icon||data.type.toLowerCase()}">
        <span class="contactText">${data.contact}</span>
    </a>`;

const activityDateTemplate = (data) => html`
    <span class="date" data-empty="${intBool(!data.date)}">${data.date}</span>`;
const descriptionListItemTemplate = (data) => html`
    <li class="descriptionItem">${data.text}</li>`;
const descriptionListTemplate = (data) => html`
    <ul class="description">${data.items}</ul>`;
const descriptionTextTemplate = (data) => html`
    <span class="description">${data.text}</span>`;
const timedActivityTemplate = (data) => html`
    <div class="activity"
            data-has-subtitle="${intBool(data.subtitle)}"
            data-has-location="${intBool(data.location)}">
        <span class="title">${data.title}</span>
        <span class="period">
            ${data.periodFrom === undefined ? "" : activityDateTemplate({date: data.periodFrom})}
            ${data.periodTo === undefined ? "" : activityDateTemplate({date: data.periodTo})}
        </span>
        <span class="subtitle">${data.subtitle}</span>
        <span class="location">${data.location}</span>
        ${data.description}
    </div>`;

const skillTemplate = (data) => html`
    <span class="skill" data-level="${data.level}">${data.name}</span>`;
const skillGroupTemplate = (data) => html`
    <div class="skillGroup">
        <div class="skillGroupName">${data.name}:</div>
        <div class="skillsContainer">${data.skills}</div>
    </div>`;

const renderName = (name) => render(name, document.querySelector('#name'));

const renderNickName = (nickname) => render(nickname, document.querySelector('#nickname'));

const renderContacts = (contactsData) => {
    render(contactsData.map((contact) => contactTemplate(contact)), document.querySelector('#contacts'));
};

const makeDescriptionList = (descriptionList) => {
    const items = descriptionList.map((item) => descriptionListItemTemplate({text: item}));
    return descriptionListTemplate({items: items});
};
const makeTimedActivity = (activityData) => {
    const data = {...activityData};
    if (Array.isArray(data.description))
        data.description = makeDescriptionList(data.description);
    else
        data.description = descriptionTextTemplate({text: data.description});
    return timedActivityTemplate(data);
};
const renderActivities = (activitiesData, element) => {
    render(activitiesData.map((activity) => makeTimedActivity(activity)), element);
};

const renderWork = (workData) => {
    const activitiesData = workData.map((job) => ({
        title: job.company,
        periodFrom: job.period[0],
        periodTo: job.period[1],
        subtitle: job.jobTitle,
        location: job.location,
        description: job.keyPoints,
    }));
    renderActivities(activitiesData, document.querySelector('#workList'));
};

const renderProjects = (projectsData) => {
    const activitiesData = projectsData.map((project) => ({
        title: project.name,
        periodFrom: project.period[0],
        periodTo: project.period[1],
        subtitle: project.subtitle,
        description: project.features,
    }));
    renderActivities(activitiesData, document.querySelector('#projectsList'));
};

const renderEducation = (educationData) => {
    const activitiesData = educationData.map((edu) => ({
        title: edu.institution,
        periodFrom: edu.period[0],
        periodTo: edu.period[1],
        location: edu.location,
        subtitle: edu.course,
        description: edu.description,
    }));
    renderActivities(activitiesData, document.querySelector('#educationList'));
};

const renderSkills = (skillsData) => {
    const skillGroupsHTML = [];
    for (const [skillGroupName, skills] of Object.entries(skillsData)) {
        const skillsHTML = skills.map((skill) => skillTemplate(skill));
        skillGroupsHTML.push(skillGroupTemplate(
            {name: skillGroupName, skills: skillsHTML}
        ));
    }
    render(skillGroupsHTML, document.querySelector('#skillList'));
};


export const renderCV = (data) => {
    renderName(data.name);
    renderNickName(data.nickname);
    renderContacts(data.contacts);
    renderWork(data.work);
    renderProjects(data.projects);
    renderEducation(data.education);
    renderSkills(data.skills);
};
